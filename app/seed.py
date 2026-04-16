from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import CharacterCard, WorldState


def seed() -> None:
    with SessionLocal() as db:
        character = db.scalar(select(CharacterCard).where(CharacterCard.name == "Guide Rowan"))
        if character is None:
            character = CharacterCard(
                name="Guide Rowan",
                description="A calm scout-mage with a field journal, a storm lantern, and a habit of noticing what others miss.",
                hard_rules=(
                    "Stay in character as Rowan.\n"
                    "Never mention being an AI or a model.\n"
                    "Respect established facts, injuries, promises, and local canon."
                ),
                style_guide="Measured, sensory, low-fantasy, and concise.",
            )
            db.add(character)

        world = db.scalar(select(WorldState).where(WorldState.name == "Glass Harbor"))
        if world is None:
            world = WorldState(
                name="Glass Harbor",
                description="A dangerous coastal city built around mirrored ruins and tide-bent causeways.",
                canon="A blue lantern warns of tide spirits. The harbor gates close at moonrise.",
                hard_rules="No modern technology.\nMagic is rare, costly, and local.",
            )
            db.add(world)

        db.commit()
        db.refresh(character)
        db.refresh(world)
        print(f"character_card_id={character.id}")
        print(f"world_state_id={world.id}")


if __name__ == "__main__":
    seed()
