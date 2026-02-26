from app.core.singleton import Singleton


class ServiceRegistry(Singleton):
    def __init__(self) -> None:
        self._user_service = None
        self._auth_service = None
        self._task_service = None

    @property
    def user_service(self):
        if self._user_service is None:
            from app.services.user import UserService
            self._user_service = UserService()
        return self._user_service

    @property
    def auth_service(self):
        if self._auth_service is None:
            from app.services.auth import AuthService
            self._auth_service = AuthService()
        return self._auth_service

    @property
    def task_service(self):
        if self._task_service is None:
            from app.services.task import TaskService
            self._task_service = TaskService()
        return self._task_service


registry = ServiceRegistry()
