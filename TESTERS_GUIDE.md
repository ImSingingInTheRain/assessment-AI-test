# Tester Guide: Employee Management Question

## Prerequisites
- Access to the survey builder with Editor, Draft/Publish workflow, and Questionnaire viewer.
- Ensure you can create and review pull requests generated from draft saves.

## 1. Add the Employee Management Question in the Editor
1. Open the **Editor** for the target survey configuration.
2. Navigate to the section where industry-related questions reside.
3. Add a new single-select question with the following attributes:
   - **Question key**: `q_employee_management`
   - **Prompt**: "Does your organization manage employees directly?"
   - **Response options**: `Yes`, `No`
   - **Visibility rule**: Display only when `q_industry` includes **Public sector**.
4. Confirm the conditional visibility in the Editor preview.

**Screenshot Placeholder:**
![Editor setup placeholder](path/to/editor-screenshot.png)

**Expected Outcome:**
- The new `q_employee_management` question is present and set to Yes/No.
- The visibility condition is configured to reference `q_industry` with the "Public sector" value.

## 2. Save Draft, Review Pull Request, and Publish
1. Click **Save Draft** to generate the draft change. Verify a pull request (PR) is created.
2. Open the PR and review the diff to ensure only the intended question changes are included.
3. Approve or merge the PR per workflow, then return to the Editor.
4. Click **Publish** to make the changes live.

**Screenshot Placeholder:**
![Draft PR review placeholder](path/to/pr-review-screenshot.png)

**Expected Outcome:**
- Saving the draft creates a PR containing the new question and visibility rule.
- Publishing completes without errors once the PR is verified.

## 3. Verify Question Behavior in the Questionnaire
1. Open the **Questionnaire** view.
2. Set `q_industry` to a value that includes **Public sector** and confirm `q_employee_management` becomes visible.
3. Change `q_industry` to a value that does **not** include **Public sector** and confirm `q_employee_management` hides.

**Screenshot Placeholder:**
![Questionnaire behavior placeholder](path/to/questionnaire-screenshot.png)

**Expected Outcome:**
- `q_employee_management` appears only when `q_industry` is set to include "Public sector".
- The question hides immediately when the condition is no longer satisfied.
