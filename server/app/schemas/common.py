from pydantic import BaseModel, ConfigDict, Field

MIN_BBOX_SIDE = 1


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=MIN_BBOX_SIDE)
    h: int = Field(ge=MIN_BBOX_SIDE)
