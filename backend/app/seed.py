from app.core.database import SessionLocal, Base, engine
from app import models  # noqa: F401
from app.models.base import (
    Team,
    Agent,
    Workspace,
    Folder,
    RiskLevel,
    ClearanceLevel,
)


def get_or_create_team(db, name: str) -> Team:
    team = db.query(Team).filter(Team.name == name).first()
    if team:
        return team

    team = Team(name=name)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def get_or_create_workspace(db, name: str, team_id: str) -> Workspace:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.name == name, Workspace.team_id == team_id)
        .first()
    )
    if workspace:
        return workspace

    workspace = Workspace(name=name, team_id=team_id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def get_or_create_agent(
    db,
    name: str,
    team_id: str,
    role: str,
    risk_level: RiskLevel,
    autonomy_level: int,
    clearance_level: ClearanceLevel,
) -> Agent:
    agent = db.query(Agent).filter(Agent.name == name).first()
    if agent:
        return agent

    agent = Agent(
        name=name,
        team_id=team_id,
        role=role,
        risk_level=risk_level,
        autonomy_level=autonomy_level,
        clearance_level=clearance_level,
        status="active",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def get_or_create_folder(
    db,
    name: str,
    workspace_id: str,
    parent_folder_id: str | None = None,
) -> Folder:
    folder = (
        db.query(Folder)
        .filter(
            Folder.name == name,
            Folder.workspace_id == workspace_id,
            Folder.parent_folder_id == parent_folder_id,
        )
        .first()
    )
    if folder:
        return folder

    folder = Folder(
        name=name,
        workspace_id=workspace_id,
        parent_folder_id=parent_folder_id,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def seed():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        team_a = get_or_create_team(db, "Team A")
        team_b = get_or_create_team(db, "Team B")

        workspace_a = get_or_create_workspace(db, "Workspace Team A", team_a.id)
        get_or_create_workspace(db, "Workspace Team B", team_b.id)

        get_or_create_agent(
            db=db,
            name="synthetic-data-agent",
            team_id=team_a.id,
            role="generator",
            risk_level=RiskLevel.low,
            autonomy_level=4,
            clearance_level=ClearanceLevel.internal,
        )

        get_or_create_agent(
            db=db,
            name="data-agent",
            team_id=team_a.id,
            role="processor",
            risk_level=RiskLevel.medium,
            autonomy_level=3,
            clearance_level=ClearanceLevel.confidential,
        )

        get_or_create_agent(
            db=db,
            name="research-agent",
            team_id=team_a.id,
            role="analyst",
            risk_level=RiskLevel.medium,
            autonomy_level=3,
            clearance_level=ClearanceLevel.confidential,
        )

        get_or_create_agent(
            db=db,
            name="code-agent",
            team_id=team_a.id,
            role="code-generator",
            risk_level=RiskLevel.high,
            autonomy_level=3,
            clearance_level=ClearanceLevel.confidential,
        )

        get_or_create_agent(
            db=db,
            name="security-agent",
            team_id=team_a.id,
            role="security",
            risk_level=RiskLevel.high,
            autonomy_level=4,
            clearance_level=ClearanceLevel.restricted,
        )

        get_or_create_agent(
            db=db,
            name="qa-agent",
            team_id=team_a.id,
            role="qa",
            risk_level=RiskLevel.medium,
            autonomy_level=3,
            clearance_level=ClearanceLevel.confidential,
        )

        datasets = get_or_create_folder(db, "datasets", workspace_a.id)
        get_or_create_folder(db, "incoming", workspace_a.id, datasets.id)
        get_or_create_folder(db, "processed", workspace_a.id, datasets.id)

        reports = get_or_create_folder(db, "reports", workspace_a.id)
        get_or_create_folder(db, "research", workspace_a.id, reports.id)
        get_or_create_folder(db, "security", workspace_a.id, reports.id)
        get_or_create_folder(db, "qa", workspace_a.id, reports.id)

        build = get_or_create_folder(db, "build", workspace_a.id)
        get_or_create_folder(db, "code", workspace_a.id, build.id)

        get_or_create_folder(db, "quarantine", workspace_a.id)

        print("Seed completed successfully.")
        print("Created Team A, Team B, agents, workspaces and folders.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()