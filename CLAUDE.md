# Directory structure

Each layer answers "what" for the layer below and "how" for the layer above. A specification at any level describes the "what" for the next level down — customer needs define "what," system decomposition defines "how," and that decomposition becomes the "what" for component-level specs.

## Layer 1 : Stakeholder intent

* doc/requirements/ : business goals, user needs, immutable constraints

## Layer 2 : Behavioral specification

* doc/requirements/stories/ : user stories with acceptance criteria
* doc/features/ : what and why, design rationale

## Layer 3 : Design specification

* doc/architecture/ : how, at design level
* specification/ : derived from architecture, authorative for implementation

## Layer 4 : Implementation specification

* tasks/ : detailed plan for implementation

## Layer 5 : Implementation

* src/
* test/
* commands/ : slash command prompt files (agentic workflows)
