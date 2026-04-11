---
name: cleanup-test-data
enabled: true
event: stop
pattern: .*
---

🧹 **Test Data Cleanup Check**

Before stopping: did this session write any **dummy, mock, or test data** to a **production database or production files**?

If yes, you MUST:
1. **Delete** all inserted test rows (e.g. `runs delete <id>`, SQL DELETE, rollback)
2. **Remove** any test files created in production directories
3. **Verify** the production state is restored (run `analyze stats` or equivalent)
4. **Confirm** to the user that cleanup is complete — BEFORE reporting success

Do not report a test as successful until the production environment is clean.
