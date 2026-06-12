# AI/RAG Human Review Scorecard

Score each generated view from 1-10.

Scenarios to inspect:

- Simple RAG assistant
- RAG ingestion + retrieval
- Agent with 12 tools
- Private Bedrock/OpenSearch access
- Traditional order service + AI assistant
- Multi-agent workflow

Criteria:

- AWS semantic correctness
- AI/RAG semantic correctness
- Readability
- View selection
- Edge cleanliness
- Usefulness for architecture review

Pass criteria:

- No primary view below 8/10
- No critical semantic mistakes
- No managed services inside VPC incorrectly
- No messy all-in-one AI diagrams
- No hidden AI flows
