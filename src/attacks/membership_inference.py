"""
Membership Inference Attack (MIA) against Healthcare Diagnostic Models.
Evaluates privacy leakage (Shokri et al., Yeom et al.):
- An adversary determines whether an individual patient's record was part of the training cohort.
- In medical environments, membership leakage confirms a patient received treatment for a sensitive disease.
- Computes Attack Accuracy, Precision, Recall, and ROC-AUC.
- Shows how Differential Privacy eliminates the generalization gap, rendering MIA ineffective.
"""

from typing import Dict, Tuple, List, Optional
import numpy as np
import torch
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.linear_model import LogisticRegression
from src.models.disease_predictor import DiseasePredictor


class MembershipInferenceAttacker:
    """
    Simulates Black-Box and Gray-Box Membership Inference Attacks
    exploiting prediction loss, prediction entropy, and confidence distributions.
    """
    def __init__(self, target_model: DiseasePredictor):
        self.target_model = target_model

    def extract_attack_features(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        """
        Extracts attack vectors for each patient record:
        [prob_class_0, prob_class_1, cross_entropy_loss, prediction_entropy, margin]
        """
        self.target_model.eval()
        with torch.no_grad():
            x_t = torch.tensor(X, dtype=torch.float32)
            logits = self.target_model(x_t).squeeze(-1)
            p1 = torch.sigmoid(logits).cpu().numpy()
            p0 = 1.0 - p1

        y_flat = y.ravel().astype(float)
        # Avoid log(0)
        eps = 1e-7
        p1_clipped = np.clip(p1, eps, 1.0 - eps)
        p0_clipped = np.clip(p0, eps, 1.0 - eps)

        # Cross entropy loss per sample
        bce_loss = -(y_flat * np.log(p1_clipped) + (1.0 - y_flat) * np.log(p0_clipped))

        # Prediction entropy
        entropy = -(p1_clipped * np.log(p1_clipped) + p0_clipped * np.log(p0_clipped))

        # Margin: distance from decision threshold 0.5
        margin = np.abs(p1 - 0.5)

        # Combined attack feature matrix
        attack_features = np.column_stack([
            p1,
            bce_loss,
            entropy,
            margin
        ])
        return attack_features

    def evaluate_attack(
        self,
        train_X: np.ndarray,
        train_y: np.ndarray,
        test_X: np.ndarray,
        test_y: np.ndarray,
        seed: int = 42
    ) -> Dict[str, float]:
        """
        Trains a shadow meta-classifier to predict membership:
        Label 1: Training Set Member (Patient data was used to train model)
        Label 0: Non-Member (Unseen patient record)
        """
        # Balance sample counts between members and non-members
        n_samples = min(len(train_X), len(test_X))
        
        idx_train = np.random.choice(len(train_X), n_samples, replace=False)
        idx_test = np.random.choice(len(test_X), n_samples, replace=False)

        feat_members = self.extract_attack_features(train_X[idx_train], train_y[idx_train])
        feat_non_members = self.extract_attack_features(test_X[idx_test], test_y[idx_test])

        X_attack = np.vstack([feat_members, feat_non_members])
        y_attack = np.hstack([np.ones(n_samples), np.zeros(n_samples)])

        # Split attack data 50/50 for shadow training and attack evaluation
        perm = np.random.permutation(len(y_attack))
        split_pt = len(y_attack) // 2

        train_att_idx = perm[:split_pt]
        test_att_idx = perm[split_pt:]

        # Train meta-classifier (Logistic Regression attacker)
        attacker_clf = LogisticRegression(max_iter=500, random_state=seed)
        attacker_clf.fit(X_attack[train_att_idx], y_attack[train_att_idx])

        # Evaluate attack on held-out attack records
        preds = attacker_clf.predict(X_attack[test_att_idx])
        probs = attacker_clf.predict_proba(X_attack[test_att_idx])[:, 1]
        y_true = y_attack[test_att_idx]

        acc = float(accuracy_score(y_true, preds))
        prec = float(precision_score(y_true, preds, zero_division=0))
        rec = float(recall_score(y_true, preds, zero_division=0))
        f1 = float(f1_score(y_true, preds, zero_division=0))
        try:
            auc = float(roc_auc_score(y_true, probs))
        except Exception:
            auc = 0.5

        # Privacy vulnerability rating
        # 50% = Perfect privacy (Pure random guess)
        # > 65% = Vulnerable
        # > 75% = High Privacy Breach
        privacy_leakage_score = max(0.0, (acc - 0.5) * 200.0) # 0 to 100 scale

        return {
            "attack_accuracy": round(acc * 100, 2),
            "attack_precision": round(prec * 100, 2),
            "attack_recall": round(rec * 100, 2),
            "attack_f1": round(f1 * 100, 2),
            "attack_auc": round(auc, 4),
            "privacy_leakage_score": round(privacy_leakage_score, 2),
            "vulnerability_level": "CRITICAL" if acc > 0.75 else ("MODERATE" if acc > 0.60 else "PROTECTED")
        }
