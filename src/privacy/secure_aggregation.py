"""
Secure Aggregation Protocol for Decentralized Healthcare Systems.
Implements pairwise additive secret masking (Bonawitz et al. principles):
- Client pairs generate zero-sum complementary mask vectors.
- Individual updates are completely obscured from the central aggregation server.
- The server aggregates masked weights, causing masks to cancel out perfectly to zero.
"""

from typing import Dict, List, Tuple, Optional
import copy
import numpy as np
import torch


class SecureAggregator:
    """
    Simulates multi-party secure aggregation with pairwise zero-sum masking.
    Ensures honest-but-curious servers or eavesdroppers cannot view individual hospital updates.
    """
    def __init__(self, client_ids: List[str]):
        self.client_ids = sorted(client_ids)
        self.num_clients = len(client_ids)

    def generate_pairwise_masks(
        self,
        parameter_shapes: Dict[str, torch.Size],
        seed: int = 1337
    ) -> Dict[str, Dict[str, torch.Tensor]]:
        """
        Generates pairwise complementary random masks for all hospital nodes.
        For every pair (i, j) with i < j, generates random mask R_ij.
        Client i adds +R_ij, Client j subtracts -R_ij.
        Sum of all masks across all clients is identically zero.
        """
        rng = np.random.default_rng(seed)
        client_masks: Dict[str, Dict[str, torch.Tensor]] = {
            cid: {name: torch.zeros(shape) for name, shape in parameter_shapes.items()}
            for cid in self.client_ids
        }

        # Pairwise negotiation
        for idx_i, cid_i in enumerate(self.client_ids):
            for idx_j in range(idx_i + 1, self.num_clients):
                cid_j = self.client_ids[idx_j]

                # Generate shared random noise vector for each parameter tensor
                for name, shape in parameter_shapes.items():
                    # Generate deterministic pseudorandom mask for the pair
                    mask_data = rng.standard_normal(size=tuple(shape)).astype(np.float32)
                    mask_tensor = torch.tensor(mask_data)

                    # Add to client i, subtract from client j
                    client_masks[cid_i][name] += mask_tensor
                    client_masks[cid_j][name] -= mask_tensor

        return client_masks

    def mask_client_update(
        self,
        update: Dict[str, torch.Tensor],
        mask: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """Obscures client gradient/parameter update with its complementary mask."""
        masked_update = {}
        for name, tensor in update.items():
            masked_update[name] = tensor + mask[name]
        return masked_update

    def aggregate_masked_updates(
        self,
        masked_updates: List[Dict[str, torch.Tensor]],
        weights: Optional[List[float]] = None
    ) -> Dict[str, torch.Tensor]:
        """
        Server sums all masked updates.
        Because all pairwise masks sum to zero, the result is the unadulterated aggregate sum!
        """
        num_updates = len(masked_updates)
        if num_updates == 0:
            raise ValueError("No updates provided for aggregation.")

        if weights is None:
            weights = [1.0 / num_updates] * num_updates
        else:
            total_w = sum(weights)
            weights = [w / total_w for w in weights]

        param_names = masked_updates[0].keys()
        aggregated = {
            name: torch.zeros_like(masked_updates[0][name])
            for name in param_names
        }

        for i, client_update in enumerate(masked_updates):
            w = weights[i]
            for name in param_names:
                aggregated[name] += client_update[name] * w

        return aggregated

    @staticmethod
    def measure_masking_secrecy(
        raw_update: Dict[str, torch.Tensor],
        masked_update: Dict[str, torch.Tensor]
    ) -> Dict[str, float]:
        """
        Quantifies the mathematical obscurity introduced by secure aggregation.
        Computes Pearson correlation and Relative Frobenius Distance between raw and masked update.
        """
        raw_flat = torch.cat([v.flatten() for v in raw_update.values()]).cpu().numpy()
        masked_flat = torch.cat([v.flatten() for v in masked_update.values()]).cpu().numpy()

        # Correlation between raw update and what the server sees
        if np.std(raw_flat) > 1e-7 and np.std(masked_flat) > 1e-7:
            corr = float(np.corrcoef(raw_flat, masked_flat)[0, 1])
        else:
            corr = 0.0

        diff_norm = float(np.linalg.norm(raw_flat - masked_flat))
        raw_norm = float(np.linalg.norm(raw_flat))

        return {
            "correlation_with_raw": round(corr, 5),
            "distortion_norm": round(diff_norm, 4),
            "relative_distortion": round(diff_norm / max(raw_norm, 1e-6), 4)
        }
