"""
Federated Training Orchestrator.
Coordinates the federated training loop across hospital nodes:
- Round-by-round dispatch of global parameters.
- Execution of localized SGD and differential privacy at hospital nodes.
- Central aggregation with optional secure aggregation.
- Real-time logging of diagnostic metrics and consumed privacy budget.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np
from src.federated.client import HospitalClient
from src.federated.server import FederatedServer
from src.privacy.differential_privacy import DifferentialPrivacyEngine


class FederatedTrainer:
    """Orchestrates multi-hospital federated training."""

    def __init__(
        self,
        server: FederatedServer,
        clients: List[HospitalClient],
        global_test_X: np.ndarray,
        global_test_y: np.ndarray
    ):
        self.server = server
        self.clients = clients
        self.global_test_X = global_test_X
        self.global_test_y = global_test_y
        self.history: List[Dict[str, any]] = []

    def run_training(
        self,
        num_rounds: int = 15,
        local_epochs: int = 3,
        batch_size: int = 16,
        lr: float = 0.01
    ) -> List[Dict[str, any]]:
        """Executes full federated learning training lifecycle."""
        client_ids = [c.client_id for c in self.clients]
        self.server.initialize_secure_aggregation(client_ids)

        for r in range(1, num_rounds + 1):
            # 1. Distribute current global model parameters to all hospitals
            global_weights = self.server.get_global_weights()
            for client in self.clients:
                client.set_global_weights(global_weights)

            # 2. Local hospital training
            client_updates = []
            for client in self.clients:
                update = client.train_epoch(
                    round_num=r,
                    local_epochs=local_epochs,
                    batch_size=batch_size,
                    lr=lr
                )
                client_updates.append(update)

            # 3. Server aggregation
            agg_result = self.server.aggregate_updates(client_updates)

            # 4. Global evaluation on independent holdout cohort
            global_metrics = self.server.evaluate_global(self.global_test_X, self.global_test_y)

            # 5. Extract privacy statistics
            total_spent_eps = 0.0
            avg_sigma = 0.0
            if self.clients and self.clients[0].dp_engine is not None:
                report = self.clients[0].dp_engine.get_privacy_report()
                total_spent_eps = report["total_spent_epsilon"]
                if report["round_history"]:
                    avg_sigma = report["round_history"][-1]["sigma"]

            round_summary = {
                "round": r,
                "global_accuracy": global_metrics["accuracy"],
                "global_auc": global_metrics["auc"],
                "global_f1": global_metrics["f1"],
                "global_precision": global_metrics["precision"],
                "global_recall": global_metrics["recall"],
                "cumulative_epsilon": round(total_spent_eps, 4),
                "sigma_applied": round(avg_sigma, 4),
                "client_metrics": [
                    {
                        "client_id": u["client_id"],
                        "name": u["hospital_name"],
                        "loss": round(u["avg_loss"], 4),
                        "val_acc": round(u["val_metrics"]["accuracy"], 4),
                        "samples": u["num_samples"]
                    }
                    for u in client_updates
                ]
            }
            self.history.append(round_summary)

        return self.history
