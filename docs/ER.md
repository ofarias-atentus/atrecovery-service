# Database ER — Template Management PoC

Source of truth: `plan.md §3`. Mermaid below mirrors it (render in GitHub/VSCode).

```mermaid
erDiagram
    roles ||--o{ role_permissions : has
    permissions ||--o{ role_permissions : granted
    users ||--o{ user_roles : has
    roles ||--o{ user_roles : assigned
    users ||--o{ auth_identities : has
    template_categories ||--o{ templates : contains
    users ||--o{ templates : creates
    resources ||--o{ resource_metadata : has
    metadata_definitions ||--o{ resource_metadata : defines
    resources ||--o{ resource_group_members : in
    resource_groups ||--o{ resource_group_members : contains
    resource_groups ||--o{ group_assignments : assigned
    templates ||--o{ template_grants : grants
    resources ||--o{ resource_grants : grants
    execution_modes ||--o{ template_usages : mode
    templates ||--o{ template_usages : used
    resources ||--o{ template_usages : targets
    users ||--o{ template_usages : requests
    templates ||--o{ usage_limits : limited
    template_usages ||--o{ execution_results : reported
    processor_services ||--o{ execution_results : reports
    users ||--o{ activity_logs : performs
    permissions ||--o{ statistics_definitions : gates
```

Text version (same as plan.md §3.1):

```
[roles] 1---* [role_permissions] *---1 [permissions]
[users] 1---* [user_roles] *---1 [roles]
[users] 1---* [auth_identities]
[template_categories] 1---* [templates]
[resources] 1---* [resource_metadata] *---1 [metadata_definitions]
[resources] 1---* [resource_group_members] *---1 [resource_groups]
[resource_groups] 1---* [group_assignments] -> principal(user|role)
[templates] 1---* [template_grants]
[execution_modes] 1---* [template_usages]
[templates] 1---* [template_usages] / [templates] 1---* [usage_limits]
[template_usages] 1---* [execution_results] / [processor_services] 1---* [execution_results]
[users] 1---* [activity_logs]
```
