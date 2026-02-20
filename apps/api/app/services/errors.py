class ServiceError(Exception):
    """Base error for service layer failures."""


class ProjectNotFoundError(ServiceError):
    pass


class InvalidStageError(ServiceError):
    pass


class InvalidTransitionError(ServiceError):
    pass


class ApprovalRequiredError(ServiceError):
    pass


class ApprovalNotFoundError(ServiceError):
    pass


class RunNotFoundError(ServiceError):
    pass


class InvalidRunTransitionError(ServiceError):
    pass


class StaleArtifactsError(ServiceError):
    pass


class ChangeRequestNotFoundError(ServiceError):
    pass


class InvalidChangeStatusError(ServiceError):
    pass


class RequirementGraphNotFoundError(ServiceError):
    pass


class RequirementGraphNotApprovedError(ServiceError):
    pass


class RequirementGraphStaleError(ServiceError):
    pass


class PlanStaleError(ServiceError):
    pass
