"""Curated lab templates for the Lab Builder (phase 9, milestone 40).

A template is a *working* built-in lab presented as a starting point. Creating a draft from a template
copies the pack's content under a new lab id and title at 1.0.0, so the author edits their own lab instead
of a Mission. Templates are curated in code (not user data); each one is resolved against the latest
built-in version of its source lab at request time, so it always starts from what is actually installed.

Keep every entry valid on its own: the source pack passes `app.labtest` (empty 0, partial, solution 100),
which is exactly what the builder's own test run will check before the author can publish.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    summary: str
    services: tuple[str, ...]
    difficulty: str  # starter | intermediate | advanced
    source_lab_id: str
    highlights: tuple[str, ...]


TEMPLATES: tuple[Template, ...] = (
    Template(
        id="s3-basics",
        title="S3 basics",
        summary="Create and configure an S3 bucket: versioning, an object upload and tags.",
        services=("s3",),
        difficulty="starter",
        source_lab_id="s3-basics",
        highlights=("Create a bucket", "Turn on versioning", "Upload a website file", "Tag the bucket"),
    ),
    Template(
        id="dynamodb-basics",
        title="DynamoDB basics",
        summary="Create a DynamoDB table for orders and store the first items.",
        services=("dynamodb",),
        difficulty="starter",
        source_lab_id="dynamodb-basics",
        highlights=("Create a table", "On-demand billing", "Put and read items"),
    ),
    Template(
        id="iam-least-privilege",
        title="IAM least privilege",
        summary="Give a group of users exactly the access they need, and nothing more.",
        services=("iam",),
        difficulty="intermediate",
        source_lab_id="iam-least-privilege",
        highlights=("Groups and users", "Read a managed policy", "Attach a least-privilege policy"),
    ),
    Template(
        id="ec2-web-server",
        title="EC2 web server",
        summary="Launch an EC2 instance behind a least-privilege security group.",
        services=("ec2",),
        difficulty="intermediate",
        source_lab_id="ec2-web-server",
        highlights=("Key pair", "Security group", "Launch an instance", "Cost control"),
    ),
    Template(
        id="lambda-basics",
        title="Lambda serverless function",
        summary="Build a Lambda function that totals an order, including tax.",
        services=("lambda",),
        difficulty="intermediate",
        source_lab_id="lambda-basics",
        highlights=("Create a function", "Environment variables", "Invoke with a test event"),
    ),
    Template(
        id="iam-breakfix",
        title="IAM break-fix",
        summary="Start from a broken IAM setup and fix it without breaking the team.",
        services=("iam",),
        difficulty="advanced",
        source_lab_id="iam-breakfix",
        highlights=("Diagnose the broken state", "Remove admin rights", "Keep the team working"),
    ),
)

BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}
