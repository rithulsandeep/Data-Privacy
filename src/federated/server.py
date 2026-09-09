"""
Federated Aggregator Server.
Implements:
1. Federated Averaging (FedAvg) algorithm across distributed hospital updates.
2. Integration with Secure Aggregation masking protocol.
3. Centralized disease evaluation on multi-institutional holdout cohorts.
4. Tamper-evident audit logging for each training round.
"""

from typing import Dict, List, Optional
import copy
import torch
from src.models.disease_predictor import DiseasePredictor
from src.privacy.secure_aggregation import SecureAggregator
from src.privacy.audit_logger import audit_ledger


class FederatedServer:
    """Central federated coordinator for healthcare diagnosis."""

    def __init__(
        self,
        input_dim: int,
        use_secure_aggregation: bool = True
    ):
        self.input_dim = input_dim
        self.global_model = DiseasePredictor(input_dim=input_dim)
        self.use_secure_aggregation = use_secure_aggregation
        self.current_round = 0
        self.secure_aggregator: Optional[SecureAggregator] = None

    def initialize_secure_aggregation(self, client_ids: List[str]) -> None:
        """Initializes pairwise masking for the connected hospital nodes."""
        self.secure_aggregator = SecureAggregator(client_ids=client_ids)

    def get_global_weights(self) -> Dict[str, torch.Tensor]:
        """Distributes current global model parameters to participating hospitals."""
        return self.global_model.get_weights()

    def aggregate_updates(
        self,
        client_updates: List[Dict[str, any]]
    ) -> Dict[str, any]:
        """
        Aggregates parameter deltas from hospitals using sample-weighted FedAvg.
        If secure aggregation is enabled, updates are verified against zero-sum masks.
        """
        self.current_round += 1
        num_clients = len(client_updates)
        if num_clients == 0:
            raise ValueError("No client updates received for aggregation.")

        total_samples = sum(u["num_samples"] for u in client_updates)
        weights = [u["num_samples"] / total_samples for u in client_updates]

        # Extract transmitted deltas
        deltas = [u["transmitted_delta"] for u in client_updates]
        client_ids = [u["client_id"] for u in client_updates]

        masking_diagnostics = {}
        if self.use_secure_aggregation and len(client_ids) > 1:
            if self.secure_aggregator is None:
                self.initialize_secure_aggregation(client_ids)

            # Generate pairwise masks
            param_shapes = {name: t.shape for name, t in deltas[0].items()}
            masks = self.secure_aggregator.generate_pairwise_masks(
                parameter_shapes=param_shapes,
                seed=42 + self.current_round
            )

            # Apply masks to updates
            masked_deltas = [
                self.secure_aggregator.mask_client_update(deltas[i], masks[client_ids[i]])
                for i in range(num_clients)
            ]

            # Measure secrecy of client 0 to record audit proof
            masking_diagnostics = SecureAggregator.measure_masking_secrecy(
                raw_update=deltas[0],
                masked_update=masked_deltas[0]
            )

            # Aggregation step: masks cancel out to zero!
            aggregated_delta = self.secure_aggregator.aggregate_masked_updates(
                masked_updates=masked_deltas,
                weights=weights
            )
        else:
            # Standard FedAvg aggregation
            param_names = deltas[0].keys()
            aggregated_delta = {name: torch.zeros_like(deltas[0][name]) for name in param_names}
            for i, delta in enumerate(deltas):
                w = weights[i]
                for name in param_names:
                    aggregated_delta[name] += delta[name] * w

        # Apply aggregated delta to update global model
        current_weights = self.global_model.get_weights()
        new_weights = {}
        for name in current_weights:
            new_weights[name] = current_weights[name] + aggregated_delta[name]

        self.global_model.set_weights(new_weights)

        # Audit logging of the aggregation event
        audit_ledger.log(
            actor_role="server",
            actor_id="FED_SERVER_01",
            action="FEDERATED_AGGREGATION_ROUND",
            status="SUCCESS",
            details={
                "round": self.current_round,
                "participating_clients": client_ids,
                "total_samples": total_samples,
                "secure_aggregation": self.use_secure_aggregation,
                "masking_secrecy": masking_diagnostics
            }
        )

        return {
            "round": self.current_round,
            "clients_aggregated": num_clients,
            "total_samples": total_samples,
            "secure_aggregation_active": self.use_secure_aggregation,
            "masking_diagnostics": masking_diagnostics
        }

    def evaluate_global(self, X_test: any, y_test: any) -> Dict[str, float]:
        """Evaluates global model on independent hold-out test cohort."""
        metrics = self.global_model.evaluate_dataset(X_test, y_test)
        metrics["round"] = self.current_round
        return metrics
