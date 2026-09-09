"""
Deep Leakage from Gradients (DLG) Attack for Medical Diagnostics.
Adversarial Gradient Inversion (Zhu et al. NeurIPS):
- An adversary intercepts client gradient updates.
- Attacker optimizes synthetic patient features using gradient matching:
  Loss = || grad_dummy - grad_target ||^2 + alpha * (1 - CosineSimilarity)
- Evaluates:
    1. Feature Recovery MSE
    2. Cosine Similarity between reconstructed and ground-truth patient features
    3. Feature Recovery Rate (% within error bounds)
- Directly demonstrates the contrast between raw unprotected gradients and DP-defended gradients.
"""

from typing import Dict, Tuple, List, Optional
import copy
import numpy as np
import torch
import torch.nn as nn
from src.models.disease_predictor import DiseasePredictor


class GradientInversionAttacker:
    """
    Simulates Red-Team gradient inversion adversary targeting healthcare client updates.
    """
    def __init__(self, model_template: DiseasePredictor):
        self.model_template = model_template

    def _flatten_grads(self, grads: Dict[str, torch.Tensor]) -> torch.Tensor:
        """Flattens gradient dictionary into a single 1D vector."""
        flat_list = []
        for name in sorted(grads.keys()):
            g = grads[name]
            if g is not None:
                flat_list.append(g.reshape(-1))
        return torch.cat(flat_list)

    def attack_single_record(
        self,
        target_gradient: Dict[str, torch.Tensor],
        ground_truth_x: np.ndarray,
        ground_truth_y: float,
        num_iterations: int = 150,
        lr: float = 0.08,
        seed: int = 42
    ) -> Dict[str, any]:
        """
        Attempts to invert client gradients into raw patient features.
        Combines L2 gradient distance and cosine matching.
        """
        torch.manual_seed(seed)
        input_dim = self.model_template.input_dim

        target_model = copy.deepcopy(self.model_template)
        target_model.eval()

        # Target flattened gradient
        target_flat = self._flatten_grads(target_gradient).detach()
        target_norm = torch.norm(target_flat)

        # Dummy feature vector initialized near zero-mean Gaussian
        dummy_x = torch.randn(1, input_dim, requires_grad=True)
        dummy_y = torch.tensor([[float(ground_truth_y)]], dtype=torch.float32)

        optimizer = torch.optim.Adam([dummy_x], lr=lr)
        criterion = nn.BCEWithLogitsLoss()

        best_dummy_x = dummy_x.detach().clone()
        min_distance = float("inf")

        named_params = sorted([(name, p) for name, p in target_model.named_parameters()])

        for step in range(num_iterations):
            optimizer.zero_grad()

            pred = target_model(dummy_x)
            dummy_loss = criterion(pred, dummy_y)

            # Compute dummy gradients wrt named params
            dummy_grads = torch.autograd.grad(
                dummy_loss,
                [p for _, p in named_params],
                create_graph=True,
                retain_graph=True,
                allow_unused=True
            )

            dummy_flat_list = []
            for (name, _), g in zip(named_params, dummy_grads):
                if g is not None:
                    dummy_flat_list.append(g.reshape(-1))
                else:
                    dummy_flat_list.append(torch.zeros_like(target_gradient[name]).reshape(-1))
            dummy_flat = torch.cat(dummy_flat_list)

            # Combined L2 and directional loss
            l2_dist = torch.sum((dummy_flat - target_flat) ** 2)
            d_norm = torch.norm(dummy_flat)
            if d_norm > 1e-8 and target_norm > 1e-8:
                cos_sim = torch.dot(dummy_flat / d_norm, target_flat / target_norm)
                directional_loss = 1.0 - cos_sim
            else:
                directional_loss = 0.0

            total_match_loss = l2_dist + 0.1 * directional_loss

            total_match_loss.backward()
            optimizer.step()

            dist_val = total_match_loss.item()
            if dist_val < min_distance:
                min_distance = dist_val
                best_dummy_x = dummy_x.detach().clone()

        # Reconstruction evaluation against true patient record
        reconstructed_np = best_dummy_x.squeeze(0).numpy()
        real_np = ground_truth_x.ravel()

        mse = float(np.mean((reconstructed_np - real_np) ** 2))
        mae = float(np.mean(np.abs(reconstructed_np - real_np)))

        norm_rec = np.linalg.norm(reconstructed_np)
        norm_real = np.linalg.norm(real_np)
        if norm_rec > 1e-6 and norm_real > 1e-6:
            cosine_sim = float(np.dot(reconstructed_np, real_np) / (norm_rec * norm_real))
        else:
            cosine_sim = 0.0

        feature_accuracy = float(np.mean(np.abs(reconstructed_np - real_np) < 0.5))

        return {
            "reconstructed_features": [round(float(v), 3) for v in reconstructed_np],
            "ground_truth_features": [round(float(v), 3) for v in real_np],
            "mse": round(mse, 4),
            "mae": round(mae, 4),
            "cosine_similarity": round(cosine_sim, 4),
            "feature_recovery_rate": round(feature_accuracy * 100, 2),
            "final_matching_distance": round(min_distance, 5),
            "attack_successful": bool(cosine_sim > 0.60 and mse < 0.6)
        }

    def evaluate_inversion_resistance(
        self,
        clean_gradient: Dict[str, torch.Tensor],
        dp_gradient: Dict[str, torch.Tensor],
        ground_truth_x: np.ndarray,
        ground_truth_y: float
    ) -> Dict[str, any]:
        """
        Runs gradient inversion side-by-side on clean vs DP perturbed gradients.
        """
        clean_result = self.attack_single_record(
            clean_gradient, ground_truth_x, ground_truth_y, num_iterations=120, seed=42
        )
        dp_result = self.attack_single_record(
            dp_gradient, ground_truth_x, ground_truth_y, num_iterations=120, seed=42
        )

        privacy_gain = round(dp_result["mse"] / max(clean_result["mse"], 1e-4), 2)

        return {
            "without_dp": clean_result,
            "with_dp": dp_result,
            "privacy_gain_mse": privacy_gain,
            "reconstruction_prevented": bool(clean_result["attack_successful"] and not dp_result["attack_successful"])
        }
