from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class ApprovalStatus(str, Enum):
    pending = 'pending'      # 待复核（0 或 1 名有效签署）
    approved = 'approved'    # 双人复核完成
