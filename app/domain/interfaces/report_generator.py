from abc import ABC, abstractmethod

from app.domain.entities.summary import Summary
from app.domain.entities.research_report import ResearchReport
from app.domain.entities.research_question import ResearchQuestion


class ReportGenerator(ABC):

    @abstractmethod
    def generate(
        self,
        question: ResearchQuestion,
        summary: Summary,
    ) -> ResearchReport:
        ...