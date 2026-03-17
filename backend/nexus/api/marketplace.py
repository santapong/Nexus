"""Marketplace API — browse and manage agent listings.

Endpoints:
- GET  /api/marketplace          — Search/browse published listings
- GET  /api/marketplace/{id}     — Get listing details
- POST /api/marketplace          — Create a new listing (workspace owner)
- PUT  /api/marketplace/{id}     — Update listing
- POST /api/marketplace/{id}/publish — Publish a listing
- POST /api/marketplace/{id}/review — Submit a review
"""
from __future__ import annotations

from typing import Any

import structlog
from litestar import Controller, get, post, put
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AgentListing, MarketplaceReview

logger = structlog.get_logger()


class CreateListingRequest(BaseModel):
    """Request body for creating a new marketplace listing."""

    name: str
    description: str
    skills: list[str] = Field(default_factory=list)
    price_per_task_usd: float = 0.0


class UpdateListingRequest(BaseModel):
    """Request body for updating a marketplace listing."""

    name: str | None = None
    description: str | None = None
    skills: list[str] | None = None
    price_per_task_usd: float | None = None


class ListingResponse(BaseModel):
    """Public representation of a marketplace listing."""

    id: str
    workspace_id: str | None
    name: str
    description: str
    skills: list[str]
    price_per_task_usd: float
    is_published: bool
    rating: float
    total_reviews: int
    total_tasks_completed: int


class SubmitReviewRequest(BaseModel):
    """Request body for submitting a review on a listing."""

    rating: float = Field(ge=1.0, le=5.0)
    comment: str | None = None
    task_id: str | None = None


def _listing_to_response(listing: AgentListing) -> ListingResponse:
    """Convert an AgentListing ORM object to a ListingResponse."""
    return ListingResponse(
        id=str(listing.id),
        workspace_id=str(listing.workspace_id) if listing.workspace_id else None,
        name=listing.name,
        description=listing.description,
        skills=listing.skills or [],
        price_per_task_usd=listing.price_per_task_usd,
        is_published=listing.is_published,
        rating=listing.rating,
        total_reviews=listing.total_reviews,
        total_tasks_completed=listing.total_tasks_completed,
    )


class MarketplaceController(Controller):
    """Browse and manage agent marketplace listings."""

    path = "/marketplace"

    @get()
    async def list_listings(
        self,
        db_session: AsyncSession,
        skill: str | None = None,
        min_rating: float | None = None,
        limit: int = 50,
    ) -> list[ListingResponse]:
        """Browse published marketplace listings."""
        stmt = select(AgentListing).where(AgentListing.is_published.is_(True))
        if skill:
            stmt = stmt.where(AgentListing.skills.any(skill))
        if min_rating is not None:
            stmt = stmt.where(AgentListing.rating >= min_rating)
        stmt = stmt.limit(limit).order_by(AgentListing.rating.desc())

        result = await db_session.execute(stmt)
        listings = result.scalars().all()
        return [_listing_to_response(listing) for listing in listings]

    @get("/{listing_id:str}")
    async def get_listing(
        self, listing_id: str, db_session: AsyncSession
    ) -> ListingResponse | dict[str, str]:
        """Get details of a marketplace listing."""
        stmt = select(AgentListing).where(AgentListing.id == listing_id)
        result = await db_session.execute(stmt)
        listing = result.scalar_one_or_none()
        if listing is None:
            return {"error": "Listing not found"}
        return _listing_to_response(listing)

    @post()
    async def create_listing(
        self, data: CreateListingRequest, db_session: AsyncSession
    ) -> ListingResponse:
        """Create a new agent listing."""
        listing = AgentListing(
            name=data.name,
            description=data.description,
            skills=data.skills,
            price_per_task_usd=data.price_per_task_usd,
        )
        db_session.add(listing)
        await db_session.flush()
        await db_session.commit()

        logger.info("marketplace_listing_created", listing_id=str(listing.id))

        return _listing_to_response(listing)

    @put("/{listing_id:str}")
    async def update_listing(
        self, listing_id: str, data: UpdateListingRequest, db_session: AsyncSession
    ) -> ListingResponse | dict[str, str]:
        """Update a marketplace listing."""
        stmt = select(AgentListing).where(AgentListing.id == listing_id)
        result = await db_session.execute(stmt)
        listing = result.scalar_one_or_none()
        if listing is None:
            return {"error": "Listing not found"}

        if data.name is not None:
            listing.name = data.name
        if data.description is not None:
            listing.description = data.description
        if data.skills is not None:
            listing.skills = data.skills
        if data.price_per_task_usd is not None:
            listing.price_per_task_usd = data.price_per_task_usd

        await db_session.flush()
        await db_session.commit()

        logger.info("marketplace_listing_updated", listing_id=listing_id)

        return _listing_to_response(listing)

    @post("/{listing_id:str}/publish")
    async def publish_listing(
        self, listing_id: str, db_session: AsyncSession
    ) -> dict[str, Any]:
        """Publish a listing to the marketplace."""
        stmt = select(AgentListing).where(AgentListing.id == listing_id)
        result = await db_session.execute(stmt)
        listing = result.scalar_one_or_none()
        if listing is None:
            return {"error": "Listing not found"}

        listing.is_published = True
        await db_session.flush()
        await db_session.commit()

        logger.info("marketplace_listing_published", listing_id=listing_id)
        return {"id": listing_id, "is_published": True}

    @post("/{listing_id:str}/review")
    async def submit_review(
        self,
        listing_id: str,
        data: SubmitReviewRequest,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Submit a review for a marketplace listing."""
        stmt = select(AgentListing).where(AgentListing.id == listing_id)
        result = await db_session.execute(stmt)
        listing = result.scalar_one_or_none()
        if listing is None:
            return {"error": "Listing not found"}

        review = MarketplaceReview(
            listing_id=listing_id,
            reviewer_workspace_id=str(listing.workspace_id) if listing.workspace_id else "system",
            rating=data.rating,
            comment=data.comment,
            task_id=data.task_id,
        )
        db_session.add(review)

        # Update listing aggregate rating
        listing.total_reviews += 1
        new_rating = (
            (listing.rating * (listing.total_reviews - 1)) + data.rating
        ) / listing.total_reviews
        listing.rating = round(new_rating, 2)

        await db_session.flush()
        await db_session.commit()

        logger.info(
            "marketplace_review_submitted",
            listing_id=listing_id,
            rating=data.rating,
        )

        return {
            "listing_id": listing_id,
            "review_submitted": True,
            "new_rating": listing.rating,
        }
