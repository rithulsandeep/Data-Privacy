"""
Attribute Inference Attack (AIA) for Healthcare Records.
Simulates sensitive attribute reconstruction:
- An adversary possesses partial patient demographics (e.g., age, sex, blood pressure).
- By querying the model for diagnostic risk scores, the attacker attempts to reconstruct
  a private, withheld clinical biomarker (e.g., serum cholesterol or cardiac enzyme indicators).
- Compares reconstruction error (RMSE, MAE, R2) across Centralized vs Federated vs DP models.
"""

from typing import Dict, Tuple, List
import numpy as np
import torch
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from src.models.disease_predictor import DiseasePredictor


class AttributeInferenceAttacker:
    """
    Infers sensitive target attribute given auxiliary patient features and model predictions.
    """
    def __init__(self, target_model: DiseasePredictor, sensitive_feature_idx: int = 4):
        self.target_model = target_model
        self.sensitive_feature_idx = sensitive_feature_idx  # Default: index 4 (cholesterol)

    def evaluate_attribute_reconstruction(
        self,
        X_data: np.ndarray,
        seed: int = 42
    ) -> Dict[str, float]:
        """
        Splits features into partial public features and secret target feature.
        Trains regressor to predict sensitive feature from [public_features, model_prediction].
        """
        self.target_model.eval()
        with torch.no_grad():
            x_t = torch.tensor(X_data, dtype=torch.float32)
            logits = self.target_model(x_t).squeeze(-1)
            model_preds = torch.sigmoid(logits).cpu().numpy().reshape(-1, 1)

        # Separate sensitive target attribute from remaining partial features
        y_sensitive = X_data[:, self.sensitive_feature_idx]
        mask = np.ones(X_data.shape[1], dtype=bool)
        mask[self.sensitive_feature_idx] = False
        X_partial = X_data[:, mask]

        # Attacker's feature set: observed features + model output probability
        X_attacker = np.hstack([X_partial, model_preds])

        # Train/test split for attack
        n_samples = len(X_data)
        perm = np.random.RandomState(seed).permutation(n_samples)
        split = int(0.6 * n_samples)
        train_idx, test_idx = perm[:split], perm[split:]

        # Fit reconstruction model
        regressor = Ridge(alpha=1.0)
        regressor.fit(X_attacker[train_idx], y_sensitive[train_idx])

        # Predict sensitive attribute on test patients
        preds = regressor.predict(X_attacker[test_idx])
        y_true = y_sensitive[test_idx]

        mse = float(mean_squared_error(y_true, preds))
        mae = float(mean_absolute_error(y_true, preds))
        r2 = float(r2_score(y_true, preds))

        # Attacker advantage: how much better than mean guess
        mean_guess_mse = float(mean_squared_error(y_true, np.full_like(y_true, np.mean(y_true))))
        leakage_ratio = max(0.0, 1.0 - (mse / max(mean_guess_mse, 1e-4)))

        return {
            "reconstruction_mse": round(mse, 4),
            "reconstruction_mae": round(mae, 4),
            "r2_score": round(r2, 4),
            "attribute_leakage_index": round(leakage_ratio * 100, 2),
            "vulnerability": "HIGH" if leakage_ratio > 0.4 else ("MEDIUM" if leakage_ratio > 0.2 else "LOW")
        }
