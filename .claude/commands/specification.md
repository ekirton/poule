Switch to SPECIFICATION phase: $ARGUMENTS

Steps:
1. Run: echo "specification" > .claude/sdd-layer
2. Read the parent architecture document and relevant data model documents.
3. Only create or modify files in specification/
4. Use Design by Contract: REQUIRES/ENSURES/MAINTAINS.
5. If architecture appears wrong, file feedback in doc/architecture/feedback/ — do not modify architecture.
6. When done, tell the user to invoke /tasks or /free
