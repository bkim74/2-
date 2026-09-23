# 온순간 North Star (Founder Direction 2026-09-18 요약)

OnMoment is a lived-evidence system for self-recognition and storydoing.

가장 짧은 인간 경험: 알아채고 → 다르게 보고 → 한 번 살아보고 → 삶에서 배우고 → 살아낸 것을 원할 때 건넨다.

Causal loop: Life → Evidence → Self-Recognition → Perspective → Meaning/Compass → Choice → Storydoing → Evidence …
충분히 살아낸 것만: Journey → Lived Wisdom → Gift → 누군가의 독립적인 Storydoing.

## 핵심 원칙
- '진정한 나'는 AI가 판정하는 본질이 아니라, 살아낸 Evidence 속에서 반복해 알아차리고 선택·시험·수정하는 살아 있는 자기이해. AI가 "당신은 이런 사람"이라 확정하는 것 금지.
- 관계적 온순간: Self ↔ Relationship ↔ Storydoing ↔ Evidence (Self, 중요한 타인, 공동체, 일, 자연, 신앙/초월 — 신앙 언어는 본인이 선택할 때만).
- B0 Compass(존재방식) / B1 관계 장면 / B2 Right Moment / Bridge = 통제 가능한 작은 한 행동.
- A = Choice 이전의 evidence, Return = Choice 이후 삶이 돌려준 evidence. 성공/실패 점수 아님.
- Tension은 문제가 아니라 발견의 자리. 한 번에 하나만 foreground.
- AI is not the author of meaning. AI is the architect of attention.
  - L0 Silence / L1 Mirror / L2 Contrast / L3 Possibility(최대 2개, 가설) / L4 Choice candidate(최종 선택은 유저).
  - Maximum memory. Minimum intervention. Better retrieval, contrast, timing, question.
- 심리적 Dress Code: Reality · Agency · Compassion · Perspective · Embodiment · Overflow.
  - Concrete before abstract. Observation before interpretation. Question before conclusion. One tension at a time. Choice before advice. Small controllable action. Reality before positivity. No forced lesson/vulnerability/gift. User words before AI words.
- 조각 + 한 문장: Raw Moment = Life speaks / One Sentence = I speak back (Authorship Anchor).
- Daily UX: [조각] → [한 문장] → (필요시)[오늘 한 번] → (행동 시)[살아보니]. anti-funnel.
- Gift is overflow, not obligation. Seed → Lived → Witnessed → Gifted.
- Founder는 온순간의 첫 번째 Storydoer. 콘텐츠를 별도 마케팅 노동으로 만들지 않는다.

## 베타 실데이터에서 확인한 병목 (2026년 5~8월 13주)
- 기록 활성 14명 중 10명 카드 완료(71%), 1인 평균 27.6건.
- 자기 언어 Insight 도달 14명 중 1명(7%) → 긴 AI 해석이 '내 말'과 다음 선택으로 이어지지 않음.
- 그래서 3줄 카드(현재·바람·선택) 중심으로 단순화. 1R 목표: Insight 도달률 20%.

## 구현 원칙 (Claude Code와 일할 때)
- 대화를 통째로 넣고 "구현해" 하지 않는다. Founder Direction → 대조 → 작은 단위 구현.
- 새 기능·새 table·새 ontology·새 ADR을 먼저 만들지 않는다. 기존 CORE / INVARIANTS / Experience Contract / ADR / 코드 / DB와 먼저 대조.
- 작게 나누고, 실제 데이터를 먼저 검수하고, 기존 MVP를 깨지 않으며, 하나의 source of truth 유지.
- 알려진 운영 이슈: live supabase_migrations.schema_migrations 등록 건수와 repo migration 파일 수 불일치 확인됨(2026-09 A0 점검).
