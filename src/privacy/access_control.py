"""
Role-Based Access Control (RBAC) for Healthcare Federated Learning Infrastructure.
Enforces HIPAA Security Rule and GDPR Data Protection Principles:
- Strict separation of duties among Clinicians, Researchers, System Administrators, and Auditors.
- Least privilege access to raw patient records, local gradients, and global model weights.
"""

from enum import Enum
from typing import Set, Dict, List, Optional


class UserRole(str, Enum):
    ADMIN = "admin"                    # Chief Information Security Officer / System Architect
    PHYSICIAN = "physician"            # Attending Hospital Clinician
    RESEARCHER = "researcher"          # Public Health Epidemiologist / AI Researcher
    AUDITOR = "auditor"                # Regulatory & Compliance Privacy Auditor


class ResourceAction(str, Enum):
    VIEW_RAW_PATIENT_DATA = "view_raw_patient_data"
    TRIGGER_FL_TRAINING = "trigger_fl_training"
    MODIFY_DP_BUDGET = "modify_dp_budget"
    ACCESS_LOCAL_GRADIENTS = "access_local_gradients"
    RUN_PATIENT_INFERENCE = "run_patient_inference"
    VIEW_AGGREGATE_METRICS = "view_aggregate_metrics"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    RUN_PRIVACY_ATTACK_TEST = "run_privacy_attack_test"
    EXPORT_HEALTHCARE_REPORT = "export_healthcare_report"


class AccessControlManager:
    """RBAC policy enforcement engine for healthcare AI system."""

    # Explicit role-to-permission mapping
    ROLE_PERMISSIONS: Dict[UserRole, Set[ResourceAction]] = {
        UserRole.ADMIN: {
            ResourceAction.VIEW_RAW_PATIENT_DATA,
            ResourceAction.TRIGGER_FL_TRAINING,
            ResourceAction.MODIFY_DP_BUDGET,
            ResourceAction.ACCESS_LOCAL_GRADIENTS,
            ResourceAction.RUN_PATIENT_INFERENCE,
            ResourceAction.VIEW_AGGREGATE_METRICS,
            ResourceAction.VIEW_AUDIT_LOGS,
            ResourceAction.RUN_PRIVACY_ATTACK_TEST,
            ResourceAction.EXPORT_HEALTHCARE_REPORT
        },
        UserRole.PHYSICIAN: {
            ResourceAction.RUN_PATIENT_INFERENCE,
            ResourceAction.VIEW_RAW_PATIENT_DATA, # Local hospital records only
            ResourceAction.VIEW_AGGREGATE_METRICS,
            ResourceAction.EXPORT_HEALTHCARE_REPORT
        },
        UserRole.RESEARCHER: {
            ResourceAction.VIEW_AGGREGATE_METRICS,
            ResourceAction.RUN_PRIVACY_ATTACK_TEST,
            ResourceAction.EXPORT_HEALTHCARE_REPORT
        },
        UserRole.AUDITOR: {
            ResourceAction.VIEW_AUDIT_LOGS,
            ResourceAction.VIEW_AGGREGATE_METRICS,
            ResourceAction.RUN_PRIVACY_ATTACK_TEST,
            ResourceAction.EXPORT_HEALTHCARE_REPORT
        }
    }

    @classmethod
    def check_permission(
        cls,
        role: UserRole,
        action: ResourceAction,
        hospital_id: Optional[str] = None,
        target_hospital_id: Optional[str] = None
    ) -> bool:
        """
        Evaluates whether the given role is authorized to perform the action.
        Includes hospital tenancy validation: Physicians cannot access other hospitals' data.
        """
        allowed_actions = cls.ROLE_PERMISSIONS.get(role, set())
        if action not in allowed_actions:
            return False

        # Hospital tenancy rule: Physicians can only view their own hospital's raw data
        if action == ResourceAction.VIEW_RAW_PATIENT_DATA and role == UserRole.PHYSICIAN:
            if hospital_id and target_hospital_id and hospital_id != target_hospital_id:
                return False

        return True

    @classmethod
    def get_role_description(cls, role: UserRole) -> Dict[str, any]:
        """Returns structured metadata on role capabilities for UI presentation."""
        descriptions = {
            UserRole.ADMIN: "Full infrastructure administration, DP parameter configuration, and orchestration.",
            UserRole.PHYSICIAN: "Clinical diagnostic inference and local patient management. Inter-hospital data locked.",
            UserRole.RESEARCHER: "Epidemiological model evaluation on aggregated data. Zero raw patient access.",
            UserRole.AUDITOR: "Cryptographic audit trail verification, privacy leakage analysis, and regulatory reporting."
        }
        permissions = [p.value for p in cls.ROLE_PERMISSIONS.get(role, set())]
        return {
            "role": role.value,
            "description": descriptions.get(role, ""),
            "permissions": permissions
        }


# Convenience module instances
access_control_manager = AccessControlManager()
access_controller = AccessControlManager()
