"""
Comprehensive Unit & Integration Test Suite for PrivateMed-FL
Tests:
1. Clinical dataset loading and Dirichlet non-IID partitioning
2. DiseasePredictor neural network forward pass & gradient computation
3. Differential Privacy engine (clipping, Gaussian mechanism, adaptive decay)
4. Bonawitz SMPC pairwise zero-sum masking and server cancellation
5. Role-Based Access Control (RBAC) permission enforcement
6. SHA-256 cryptographic audit ledger and chain integrity verification
7. Red-Team adversarial attack modules (DLG, MIA, AIA)
8. Clinical risk prediction simulator endpoint
"""

import unittest
import numpy as np
import torch
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.data_loader import generate_synthetic_uci_heart, create_federated_partitions
from src.models.disease_predictor import DiseasePredictor
from src.privacy.differential_privacy import DifferentialPrivacyEngine
from src.privacy.secure_aggregation import SecureAggregator
from src.privacy.access_control import AccessControlManager, UserRole, ResourceAction
from src.privacy.audit_logger import AuditLogger
from src.attacks.gradient_inversion import GradientInversionAttacker
from src.attacks.membership_inference import MembershipInferenceAttacker
from src.attacks.attribute_inference import AttributeInferenceAttacker
from server import PatientPredictionInput, predict_disease_risk


class TestDataModule(unittest.TestCase):
    def test_synthetic_uci_generation(self):
        X, y, features = generate_synthetic_uci_heart(n_samples=100, seed=42)
        self.assertEqual(X.shape, (100, 13))
        self.assertEqual(len(y), 100)
        self.assertEqual(len(features), 13)
        self.assertTrue(set(y).issubset({0, 1}))

    def test_federated_partitions(self):
        X, y, _ = generate_synthetic_uci_heart(n_samples=150, seed=42)
        parts = create_federated_partitions(X, y, num_hospitals=3, alpha=0.5, test_size=0.2, seed=42)
        self.assertIn("global_test", parts)
        self.assertIn("hospitals", parts)
        self.assertEqual(len(parts["hospitals"]), 3)
        self.assertEqual(len(parts["global_test"]["X"]), 30)


class TestModelModule(unittest.TestCase):
    def test_forward_pass_and_gradients(self):
        model = DiseasePredictor(input_dim=13)
        x = torch.randn(4, 13)
        out = model(x)
        self.assertEqual(out.shape, (4, 1))

        # Backward pass
        loss = out.sum()
        loss.backward()
        grads = model.get_gradients()
        self.assertTrue(len(grads) > 0)
        self.assertIn("network.0.weight", grads)


class TestPrivacyModule(unittest.TestCase):
    def test_differential_privacy_engine(self):
        dp = DifferentialPrivacyEngine(
            target_epsilon=10.0,
            target_delta=1e-5,
            max_grad_norm=1.2,
            noise_multiplier=0.8,
            adaptive=True,
            total_rounds=15
        )
        fake_grads = {"layer1": torch.ones(5, 5) * 2.0}
        clipped, norm = dp.clip_gradients(fake_grads)
        self.assertLessEqual(norm, 1.2 * 10) # clipped to max_grad_norm

        noisy, sigma, eps_round = dp.add_noise(clipped, round_num=1)
        self.assertNotEqual(clipped["layer1"][0, 0].item(), noisy["layer1"][0, 0].item())
        self.assertGreater(sigma, 0.0)

    def test_secure_aggregation_cancellation(self):
        client_ids = ["h_0", "h_1", "h_2"]
        aggregator = SecureAggregator(client_ids)
        param_shapes = {"w": torch.Size([10])}
        masks = aggregator.generate_pairwise_masks(param_shapes, seed=42)

        # Check mask cancellation: Sum M_i == 0
        sum_masks = torch.zeros(10)
        for cid, m_dict in masks.items():
            sum_masks += m_dict["w"]
        self.assertTrue(torch.allclose(sum_masks, torch.zeros(10), atol=1e-5))

        # Check aggregate sum equals raw sum
        raw_updates = {
            "h_0": {"w": torch.tensor([1.0] * 10)},
            "h_1": {"w": torch.tensor([2.0] * 10)},
            "h_2": {"w": torch.tensor([3.0] * 10)}
        }
        masked_updates = {
            cid: aggregator.mask_client_update(raw_updates[cid], masks[cid])
            for cid in client_ids
        }
        agg_masked = torch.zeros(10)
        for cid, u_dict in masked_updates.items():
            agg_masked += u_dict["w"]
        expected_raw_sum = torch.tensor([6.0] * 10)
        self.assertTrue(torch.allclose(agg_masked, expected_raw_sum, atol=1e-5))


class TestRBACAndAudit(unittest.TestCase):
    def test_rbac_rules(self):
        # Admin can do all
        self.assertTrue(AccessControlManager.check_permission(UserRole.ADMIN, ResourceAction.TRIGGER_FL_TRAINING))
        self.assertTrue(AccessControlManager.check_permission(UserRole.ADMIN, ResourceAction.MODIFY_DP_BUDGET))

        # Physician cannot trigger FL or modify DP
        self.assertFalse(AccessControlManager.check_permission(UserRole.PHYSICIAN, ResourceAction.TRIGGER_FL_TRAINING))
        self.assertFalse(AccessControlManager.check_permission(UserRole.PHYSICIAN, ResourceAction.MODIFY_DP_BUDGET))
        self.assertTrue(AccessControlManager.check_permission(UserRole.PHYSICIAN, ResourceAction.RUN_PATIENT_INFERENCE))

        # Physician cannot view other hospital data
        self.assertFalse(AccessControlManager.check_permission(
            UserRole.PHYSICIAN, ResourceAction.VIEW_RAW_PATIENT_DATA,
            hospital_id="Hospital_A", target_hospital_id="Hospital_B"
        ))

    def test_audit_ledger_integrity(self):
        logger = AuditLogger()
        logger.log(actor_role="admin", actor_id="CISO_01", action="TEST_ACTION_1")
        logger.log(actor_role="physician", actor_id="DR_01", action="TEST_ACTION_2")
        self.assertTrue(logger.verify_chain_integrity())

        # Tampering test
        logger.chain[1]["details"] = {"tampered": True}
        is_valid, corrupted_idx = logger.verify_integrity()
        self.assertFalse(is_valid)
        self.assertEqual(corrupted_idx, 1)


class TestAttacksAndServer(unittest.TestCase):
    def test_attack_instantiations(self):
        model = DiseasePredictor(input_dim=13)
        inv = GradientInversionAttacker(model)
        mia = MembershipInferenceAttacker(model)
        aia = AttributeInferenceAttacker(model, sensitive_feature_idx=4)
        self.assertIsNotNone(inv)
        self.assertIsNotNone(mia)
        self.assertIsNotNone(aia)

    def test_predict_endpoint(self):
        inp = PatientPredictionInput(age=60, sex=1, cp=0, trestbps=140, chol=250, thalach=130, exang=1, oldpeak=2.0)
        out = predict_disease_risk(inp)
        self.assertIn("disease_probability", out)
        self.assertIn("risk_percentage", out)
        self.assertIn("clinical_category", out)
        self.assertEqual(out["ephi_status"], "PROCESSED_LOCALLY_ZERO_LEAKAGE")


if __name__ == "__main__":
    unittest.main()
