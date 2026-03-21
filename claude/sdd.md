# Spec-Driven Development Process

## Core Principles

The documents form a **chain of authority**. While working on one layer, do not edit related documents above or below that layer. Do not invent requirements or infer unnecessary details; ask the user when ambiguities exist.

The exception is Stage 8 (implementation): you have wide latitude to implement code but must not change tests or specs.

## Stages

### Stage 1: Requirements

Write a detailed PRD to `doc/requirements/`.

### Stage 2: Features

Propagate requirements down to `doc/features/`. If a problem with the requirements is detected, do **not** edit requirements — surface the issue to the user instead.

### Stage 3: Architecture

Propagate features down to `doc/architecture/`. If a problem is found in upstream documents, do **not** edit them — surface the issue to the user instead.

### Stage 4: Specifications

Propagate architecture down to `specification/`. If a problem is identified with the architecture, do **not** edit the architecture documents. Instead, write a detailed description to a file in `doc/architecture/feedback/` and **stop**. If any architecture feedback is written, notify the user and stop.

When modifying existing specifications, take note of the blast radius (i.e., specifications that are changed).

### Stage 5: Tests

Update tests within the blast radius and create tests for new specifications. When writing tests, do **not** change the specifications. If a problem is discovered, write to `specification/feedback/` instead.

### Stage 6: Specification Feedback Resolution

Check if any `specification/feedback/` files exist. If none, skip this stage.

For each feedback item, think hard about it:
- If **valid**: resolve by fixing the specification.
- If **invalid and the test is the problem**: resolve by fixing the test.
- If **invalid and the architecture is the problem**: resolve by writing to `doc/architecture/feedback/`.

If any architecture feedback was given, notify the user and **stop**. Otherwise, return to Stage 5.

### Stage 7: Test Feedback Resolution

Check if any `test/feedback/` files exist. If none, skip this stage.

For each feedback item:
- If **valid**: fix the test.
- If **invalid**: write a detailed description to `specification/feedback/`, notify the user, and **stop**.

### Stage 8: Implementation

Write the implementation to pass the tests. Do **not** change any tests or specifications. If a problem is encountered, use the file-feedback mechanism.

After implementing as much as possible:
- If any specification feedback was given, go to Stage 6.
- If any test feedback was given, go to Stage 7.

### Stage 9: Documentation and Delivery

Update `README.md` and `DEVELOPMENT.md` as appropriate. Commit and push but do **not** make a PR.

If any feedback files exist, notify the user and **stop**.
