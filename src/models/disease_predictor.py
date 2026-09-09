"""
Medical Diagnostic Neural Network Model.
Designed specifically to support Differential Privacy and Federated Averaging:
- Uses LayerNorm / Dropout instead of BatchNorm (BatchNorm violates DP independence assumptions)
- Exposes clean weight extraction, gradient extraction, and comprehensive diagnostic evaluation.
"""

from typing import Dict, Tuple, List, Optional
import copy
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score


class DiseasePredictor(nn.Module):
    """
    Diagnostic MLP for tabular clinical indicators.
    Architecture:
      Input (dim) -> Linear(64) -> LeakyReLU -> Dropout(0.2)
                  -> Linear(32) -> LeakyReLU -> Dropout(0.1)
                  -> Linear(16) -> LeakyReLU
                  -> Linear(1) (Logits)
    """
    def __init__(self, input_dim: int, hidden_dims: Tuple[int, ...] = (64, 32, 16), dropout: float = 0.2):
        super().__init__()
        self.input_dim = input_dim

        layers = []
        prev_dim = input_dim
        for h_dim in hidden_dims:
            layers.append(nn.Linear(prev_dim, h_dim))
            layers.append(nn.LeakyReLU(0.1))
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
            prev_dim = h_dim

        layers.append(nn.Linear(prev_dim, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Returns probability of positive disease diagnosis."""
        with torch.no_grad():
            logits = self.forward(x)
            return torch.sigmoid(logits)

    def get_weights(self) -> Dict[str, torch.Tensor]:
        """Returns a deep-copied dictionary of model parameters."""
        return {name: param.detach().clone() for name, param in self.state_dict().items()}

    def set_weights(self, weights: Dict[str, torch.Tensor]) -> None:
        """Loads model weights."""
        self.load_state_dict(weights)

    def get_gradients(self) -> Dict[str, torch.Tensor]:
        """Extracts gradient tensors after backward pass."""
        grads = {}
        for name, param in self.named_parameters():
            if param.grad is not None:
                grads[name] = param.grad.detach().clone()
            else:
                grads[name] = torch.zeros_like(param)
        return grads

    def evaluate_dataset(self, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Calculates clinical diagnostic metrics: Acc, Precision, Recall, F1, AUC-ROC."""
        self.eval()
        with torch.no_grad():
            x_tensor = torch.tensor(X, dtype=torch.float32)
            logits = self.forward(x_tensor).squeeze(-1)
            probs = torch.sigmoid(logits).cpu().numpy()
            preds = (probs >= 0.5).astype(int)

        y_true = y.astype(int).ravel()
        
        # Guard against single-class cases in small batches
        try:
            auc = roc_auc_score(y_true, probs)
        except Exception:
            auc = 0.5

        return {
            "accuracy": float(accuracy_score(y_true, preds)),
            "precision": float(precision_score(y_true, preds, zero_division=0)),
            "recall": float(recall_score(y_true, preds, zero_division=0)),
            "f1": float(f1_score(y_true, preds, zero_division=0)),
            "auc": float(auc)
        }


def train_centralized_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 0.005,
    seed: int = 42
) -> Tuple[DiseasePredictor, List[Dict[str, float]]]:
    """
    Trains traditional centralized model where all hospital records are combined in one place.
    Serves as the performance and privacy baseline.
    """
    torch.manual_seed(seed)
    model = DiseasePredictor(input_dim=X_train.shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.BCEWithLogitsLoss()

    n_samples = len(X_train)
    history = []

    for epoch in range(epochs):
        model.train()
        permutation = np.random.permutation(n_samples)
        epoch_loss = 0.0
        n_batches = 0

        for i in range(0, n_samples, batch_size):
            batch_idx = permutation[i:i + batch_size]
            bx = torch.tensor(X_train[batch_idx], dtype=torch.float32)
            by = torch.tensor(y_train[batch_idx], dtype=torch.float32).unsqueeze(1)

            optimizer.zero_grad()
            out = model(bx)
            loss = criterion(out, by)
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        val_metrics = model.evaluate_dataset(X_val, y_val)
        val_metrics["epoch"] = epoch + 1
        val_metrics["loss"] = epoch_loss / max(n_batches, 1)
        history.append(val_metrics)

    return model, history
