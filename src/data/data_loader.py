"""
Medical Dataset Loader and Non-IID Federated Partitioner.
Supports:
1. 'heart_disease': 13-feature clinical diagnostic dataset (UCI Cleveland distribution)
2. 'cancer_biopsy': 30-feature clinical diagnostic dataset (Wisconsin Diagnostic)
Simulates realistic non-IID patient population splits across distributed hospital nodes.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.datasets import load_breast_cancer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


class MedicalTabularDataset(Dataset):
    """PyTorch Dataset wrapper for clinical tabular records."""
    def __init__(self, X: np.ndarray, y: np.ndarray, patient_ids: Optional[List[str]] = None):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32).unsqueeze(1)
        self.patient_ids = patient_ids or [f"PT-{i:04d}" for i in range(len(X))]

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, str]:
        return self.X[idx], self.y[idx], self.patient_ids[idx]


def generate_synthetic_uci_heart(n_samples: int = 400, seed: int = 42) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Generates realistic clinical records adhering to the UCI Cleveland Heart Disease distribution.
    Features:
    0. age: Age in years
    1. sex: 1 = male, 0 = female
    2. cp: Chest pain type (0-3)
    3. trestbps: Resting blood pressure (mm Hg)
    4. chol: Serum cholesterol (mg/dl)
    5. fbs: Fasting blood sugar > 120 mg/dl (1=true, 0=false)
    6. restecg: Resting ECG results (0, 1, 2)
    7. thalach: Maximum heart rate achieved
    8. exang: Exercise induced angina (1=yes, 0=no)
    9. oldpeak: ST depression induced by exercise
    10. slope: Slope of peak exercise ST segment (0-2)
    11. ca: Number of major vessels (0-3)
    12. thal: Thalassemia (1=normal, 2=fixed defect, 3=reversible defect)
    Target: 1 = Presence of heart disease, 0 = Absence
    """
    np.random.seed(seed)
    age = np.random.normal(54.4, 9.0, n_samples).clip(29, 77)
    sex = np.random.binomial(1, 0.68, n_samples)
    cp = np.random.choice([0, 1, 2, 3], size=n_samples, p=[0.47, 0.17, 0.28, 0.08])
    trestbps = np.random.normal(131.6, 17.5, n_samples).clip(94, 200)
    chol = np.random.normal(246.3, 51.8, n_samples).clip(126, 564)
    fbs = np.random.binomial(1, 0.15, n_samples)
    restecg = np.random.choice([0, 1, 2], size=n_samples, p=[0.49, 0.02, 0.49])
    thalach = (200 - 0.7 * age + np.random.normal(0, 15, n_samples)).clip(71, 202)
    exang = np.random.binomial(1, 0.33, n_samples)
    oldpeak = np.random.exponential(1.0, n_samples).clip(0, 6.2)
    slope = np.random.choice([0, 1, 2], size=n_samples, p=[0.46, 0.46, 0.08])
    ca = np.random.choice([0, 1, 2, 3], size=n_samples, p=[0.58, 0.22, 0.13, 0.07])
    thal = np.random.choice([1, 2, 3], size=n_samples, p=[0.06, 0.55, 0.39])

    # Realistic clinical logistic logit to compute target label
    logits = (
        0.04 * (age - 50) +
        0.6 * sex +
        0.7 * (cp == 0) +
        0.015 * (trestbps - 120) +
        0.008 * (chol - 200) +
        -0.03 * (thalach - 150) +
        0.8 * exang +
        0.5 * oldpeak +
        0.6 * (ca > 0) +
        0.7 * (thal == 3) - 1.2
    )
    prob = 1.0 / (1.0 + np.exp(-logits))
    target = (np.random.rand(n_samples) < prob).astype(int)

    feature_names = [
        "age", "sex", "cp", "trestbps", "chol", "fbs",
        "restecg", "thalach", "exang", "oldpeak", "slope", "ca", "thal"
    ]
    X = np.column_stack([
        age, sex, cp, trestbps, chol, fbs,
        restecg, thalach, exang, oldpeak, slope, ca, thal
    ])
    return X, target, feature_names


def load_clinical_dataset(dataset_name: str = "heart_disease", seed: int = 42) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Loads either heart_disease or cancer_biopsy dataset."""
    if dataset_name == "cancer_biopsy":
        data = load_breast_cancer()
        X = data.data
        y = data.target
        feature_names = list(data.feature_names)
        return X, y, feature_names
    else:
        # Default to heart disease
        return generate_synthetic_uci_heart(n_samples=450, seed=seed)


def create_federated_partitions(
    X: np.ndarray,
    y: np.ndarray,
    num_hospitals: int = 3,
    alpha: float = 0.5,
    test_size: float = 0.2,
    seed: int = 42
) -> Dict[str, Dict]:
    """
    Partitions patient data into non-IID splits across hospital nodes.
    Uses Dirichlet distribution on class proportions to simulate demographic and diagnostic imbalance.

    Returns:
        dict with:
            'global_test': {'X': ..., 'y': ..., 'patient_ids': ...}
            'hospitals': {
                'Hospital_A': {'train': {'X', 'y'}, 'val': {'X', 'y'}, 'name': 'Metro General Hospital'},
                ...
            }
    """
    np.random.seed(seed)
    n_samples = len(X)
    patient_ids = np.array([f"PT-{i:04d}" for i in range(n_samples)])

    # Stratified split for global hold-out test set
    X_train_full, X_test_global, y_train_full, y_test_global, ids_train, ids_test = train_test_split(
        X, y, patient_ids, test_size=test_size, random_state=seed, stratify=y
    )

    # Standardize features (fit on train, apply to test)
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_full)
    X_test_scaled = scaler.transform(X_test_global)

    # Non-IID Dirichlet partitioning on training samples
    hospital_names = [
        "Hospital A (Metro General)",
        "Hospital B (St. Jude Clinic)",
        "Hospital C (Highland Medical)",
        "Hospital D (Valley Health)",
        "Hospital E (Central Oncology)"
    ][:num_hospitals]

    hospital_keys = [f"hospital_{chr(65+i)}" for i in range(num_hospitals)]

    classes = np.unique(y_train_full)
    client_indices = [[] for _ in range(num_hospitals)]

    for c in classes:
        c_indices = np.where(y_train_full == c)[0]
        np.random.shuffle(c_indices)
        proportions = np.random.dirichlet(np.repeat(alpha, num_hospitals))
        proportions = np.cumsum(proportions)
        proportions = (proportions * len(c_indices)).astype(int)
        proportions[-1] = len(c_indices)

        prev = 0
        for i, bound in enumerate(proportions):
            client_indices[i].extend(c_indices[prev:bound])
            prev = bound

    hospital_data = {}
    for i, key in enumerate(hospital_keys):
        idx = np.array(client_indices[i])
        np.random.shuffle(idx)

        h_X = X_train_scaled[idx]
        h_y = y_train_full[idx]
        h_ids = ids_train[idx]

        # 80/20 train/validation split for each local hospital
        val_split = max(int(len(idx) * 0.2), 5)
        train_idx = slice(val_split, None)
        val_idx = slice(None, val_split)

        hospital_data[key] = {
            "name": hospital_names[i],
            "train": {
                "X": h_X[train_idx],
                "y": h_y[train_idx],
                "patient_ids": list(h_ids[train_idx])
            },
            "val": {
                "X": h_X[val_idx],
                "y": h_y[val_idx],
                "patient_ids": list(h_ids[val_idx])
            },
            "num_samples": len(idx),
            "positive_rate": float(np.mean(h_y))
        }

    return {
        "global_test": {
            "X": X_test_scaled,
            "y": y_test_global,
            "patient_ids": list(ids_test)
        },
        "global_train": {
            "X": X_train_scaled,
            "y": y_train_full,
            "patient_ids": list(ids_train)
        },
        "hospitals": hospital_data,
        "scaler": scaler
    }
