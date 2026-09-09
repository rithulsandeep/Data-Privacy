"""
Federated Hospital Client Node.
Simulates a localized healthcare provider (e.g. Metro General, St. Jude Clinic).
- Trains local AI model strictly within institutional boundary.
- Computes parameter updates (gradients / weight deltas).
- Applies Local Differential Privacy (gradient clipping + calibrated noise).
- Encrypts updates or adds Secure Aggregation masks before transmission.
- Never transmits raw Electronic Health Records (EHR).
"""

from typing import Dict, List, Tuple, Optional
import copy
import numpy as np
import torch
import torch.nn as nn
from src.models.disease_predictor import DiseasePredictor
from src.privacy.differential_privacy import DifferentialPrivacyEngine


class HospitalClient:
    """
    Simulated autonomous hospital node participating in federated disease prediction.
    """
    def __init__(
        self,
        client_id: str,
        hospital_name: str,
        train_X: np.ndarray,
        train_y: np.ndarray,
        val_X: np.ndarray,
        val_y: np.ndarray,
        patient_ids: List[str],
        dp_engine: Optional[DifferentialPrivacyEngine] = None
    ):
        self.client_id = client_id
        self.hospital_name = hospital_name
        self.train_X = train_X
        self.train_y = train_y
        self.val_X = val_X
        self.val_y = val_y
        self.patient_ids = patient_ids
        self.dp_engine = dp_engine

        input_dim = train_X.shape[1]
        self.model = DiseasePredictor(input_dim=input_dim)
        self.initial_weights: Optional[Dict[str, torch.Tensor]] = None

    def set_global_weights(self, global_weights: Dict[str, torch.Tensor]) -> None:
        """Synchronizes local model with global model from central aggregator."""
        self.model.set_weights(global_weights)
        self.initial_weights = copy.deepcopy(global_weights)

    def train_epoch(
        self,
        round_num: int,
        local_epochs: int = 3,
        batch_size: int = 16,
        lr: float = 0.01
    ) -> Dict[str, any]:
        """
        Executes local SGD on hospital EHR data.
        Computes weight updates: Delta_W = W_local - W_global.
        Applies Differential Privacy if configured.
        """
        if self.initial_weights is None:
            self.initial_weights = self.model.get_weights()

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        criterion = nn.BCEWithLogitsLoss()
        n_samples = len(self.train_X)

        self.model.train()
        total_loss = 0.0
        n_batches = 0

        for _ in range(local_epochs):
            perm = np.random.permutation(n_samples)
            for i in range(0, n_samples, batch_size):
                idx = perm[i:i + batch_size]
                bx = torch.tensor(self.train_X[idx], dtype=torch.float32)
                by = torch.tensor(self.train_y[idx], dtype=torch.float32).unsqueeze(1)

                optimizer.zero_grad()
                out = self.model(bx)
                loss = criterion(out, by)
                loss.backward()
                optimizer.step()

                total_loss += loss.item()
                n_batches += 1

        # Compute raw parameter delta: Delta_W = W_local - W_global
        local_weights = self.model.get_weights()
        raw_delta: Dict[str, torch.Tensor] = {}
        for name in local_weights:
            raw_delta[name] = local_weights[name] - self.initial_weights[name]

        # Apply Differential Privacy if enabled
        is_dp_applied = False
        sigma_used = 0.0
        round_epsilon = 0.0
        clip_norm = 0.0

        if self.dp_engine is not None:
            clipped_delta, clip_norm = self.dp_engine.clip_gradients(raw_delta)
            noisy_delta, sigma_used, round_epsilon = self.dp_engine.add_noise(
                clipped_delta,
                round_num=round_num,
                batch_size=batch_size,
                dataset_size=n_samples
            )
            transmitted_delta = noisy_delta
            is_dp_applied = True
        else:
            transmitted_delta = raw_delta

        val_metrics = self.evaluate_local()

        return {
            "client_id": self.client_id,
            "hospital_name": self.hospital_name,
            "raw_delta": raw_delta,
            "transmitted_delta": transmitted_delta,
            "num_samples": n_samples,
            "avg_loss": total_loss / max(n_batches, 1),
            "val_metrics": val_metrics,
            "dp_applied": is_dp_applied,
            "sigma": sigma_used,
            "round_epsilon": round_epsilon,
            "clip_norm": clip_norm
        }

    def evaluate_local(self) -> Dict[str, float]:
        """Evaluates current local model on hospital validation partition."""
        return self.model.evaluate_dataset(self.val_X, self.val_y)
