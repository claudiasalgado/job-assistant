import os
import uuid

from google.cloud import pubsub_v1

from core.models import Application, ApplicationEvent, ApplicationStatus


class EventPublisher:
    """Publica los cambios de las candidaturas en el topic que lee BigQuery (decisión 023)."""

    def __init__(self, topic: str | None = None, publisher: pubsub_v1.PublisherClient | None = None):
        topic = topic or os.environ.get("EVENTS_TOPIC")
        if not topic:
            raise RuntimeError("Falta la variable de entorno EVENTS_TOPIC (ver .env.example)")
        self._publisher = publisher or pubsub_v1.PublisherClient()
        self._topic = self._publisher.topic_path(os.environ["GOOGLE_CLOUD_PROJECT"], topic)

    def created(self, application: Application) -> None:
        self._publish(application, "created", from_status=None)

    def status_changed(self, application: Application, from_status: ApplicationStatus) -> None:
        self._publish(application, "status_changed", from_status=from_status)

    def _publish(self, application: Application, event_type: str, from_status: ApplicationStatus | None) -> None:
        event = ApplicationEvent(
            event_id=str(uuid.uuid4()),
            application_id=str(application.id),
            event_type=event_type,
            from_status=from_status,
            to_status=application.status,
            company=application.extracted.company,
            title=application.extracted.title,
            match_score=application.match.score if application.match else None,
        )
        # result() espera la confirmación de Pub/Sub: si falla, la excepción sale aquí
        self._publisher.publish(self._topic, event.model_dump_json().encode()).result(timeout=30)
