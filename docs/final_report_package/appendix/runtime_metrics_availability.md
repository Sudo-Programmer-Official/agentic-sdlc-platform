# runtime metrics availability

Observed metric-related implementation points:
- project/run metrics service: `apps/api/app/services/metrics_service.py`
- governance KPI builder: `apps/api/app/services/governance_kpis.py`
- timeline and run summary generation: `apps/api/app/services/run_timeline.py`
- context efficiency fields in context ranking trace: `apps/api/app/services/context_ranking_policy.py`

Available metric constructs include:
- recovery count, artifact count, elapsed time,
- context loaded count, context selected count, context efficiency ratio,
- run/task distribution and duration aggregates.

This appendix documents availability of metric definitions; dataset-specific numeric results should be produced from a live evaluation run snapshot.
