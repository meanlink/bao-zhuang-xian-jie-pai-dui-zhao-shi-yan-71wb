export const Role={admin:'业务负责人',analyst:'分析员',viewer:'观察员'};
export const JobStatus={queued:'排队中',running:'计算中',completed:'已完成',failed:'执行失败'};
export const ApprovalStatus={pending:'待复核',approved:'双人复核完成'};
export const ApprovalAction={'approval.sign':'复核签署','approval.revoke':'撤回签署','approval.migrated':'旧记录迁移'};
export const PausedReason={approval_revoked:'签署已撤回，等待重新复核',approval_invalid:'有效签署不足，等待重新复核',legacy_approval:'旧单人批准已失效，等待双人复核',manual:'负责人手动暂停'};
