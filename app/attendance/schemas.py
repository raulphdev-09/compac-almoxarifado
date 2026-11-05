from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class TerminalInput(StrictPayload):
    name: str = Field(min_length=1, max_length=120)
    work_id: int = Field(gt=0)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Informe o nome do terminal de teste.')
        return value


class TestAuthorizationInput(StrictPayload):
    registration: str = Field(min_length=1, max_length=120)
    terminal_id: int = Field(gt=0)
    acknowledgement: Literal['TESTE_SUPERVISIONADO']

    @field_validator('registration')
    @classmethod
    def clean_registration(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Informe a matrícula fictícia.')
        return value


class MarkInput(StrictPayload):
    authorization: str = Field(min_length=32, max_length=128)
    mark_type: Literal['ENTRADA', 'INICIO_INTERVALO', 'RETORNO_INTERVALO', 'SAIDA']
