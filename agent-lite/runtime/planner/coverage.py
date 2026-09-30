"""通用规划能力与类型模板的覆盖矩阵。"""

CORE_CAPABILITIES = {
    "task_facts": "用户事实、偏好、约束和禁止项",
    "visible_decisions": "少量会改变整体路线的用户选择",
    "hidden_details": "默认实现细节、理由和验收依据",
    "acceptance": "操作步骤、预期结果和验证方式",
    "resource_requests": "查询端资源申请和 pending 状态",
    "risks": "许可、付费、权限和阻塞项",
    "review": "复核状态、评分和缺口",
}

TEMPLATE_CAPABILITIES = {
    "web": {"browser_acceptance", "responsive", "accessibility", "visual_acceptance"},
    "web_game": {"browser_acceptance", "responsive", "state_machine", "invariants", "stress_test"},
    "crawler": {"authorization", "privacy", "source_validity", "retry_policy"},
    "timetable": {"authorization", "privacy", "source_validity", "retry_policy"},
    "software": {"module_boundaries", "permissions", "configuration", "crash_recovery"},
    "general": set(),
}


def coverage_for(template_name: str) -> dict:
    return {"core": sorted(CORE_CAPABILITIES), "specialized": sorted(TEMPLATE_CAPABILITIES.get(template_name, set()))}
