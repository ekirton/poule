# Specification Feedback: storage.md

## FTS5 Tokenizer Syntax (Section 4.1)

The spec says "Unicode tokenizer with Porter stemming" which could be interpreted as `tokenize='unicode61 porter'`. However, FTS5 requires the stemming tokenizer to wrap the base tokenizer, so the correct syntax is `tokenize='porter unicode61'`. This is because in FTS5, tokenizers are nested -- `porter` wraps `unicode61`, not the other way around.

**Suggested clarification**: Specify the exact tokenize clause: `tokenize='porter unicode61'`.
