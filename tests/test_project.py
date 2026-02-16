"""Tests for Project Context Awareness (R4)."""

import json
from pathlib import Path

import pytest

from src.meta_mcp.project import ProjectAnalyzer


class TestLanguageDetection:
    """Detect primary language from marker files."""

    def test_detect_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.language == "python"

    def test_detect_node(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.language == "node"

    def test_detect_typescript_over_node(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.language == "typescript"

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname="x"', encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.language == "rust"

    def test_no_language_detected(self, tmp_path):
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.language is None


class TestFrameworkDetection:
    """Detect frameworks from dependency files."""

    def test_detect_react(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "app", "dependencies": {"react": "^18"}}),
            encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.framework == "react"

    def test_detect_fastapi(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\ndependencies=["fastapi"]', encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.framework == "fastapi"

    def test_detect_django_from_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("django>=4.0\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.framework == "django"


class TestVCSDetection:
    """Detect version control and provider."""

    def test_detect_git(self, tmp_path):
        (tmp_path / ".git").mkdir()
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.vcs == "git"

    def test_detect_github_provider(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/user/repo.git\n',
            encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        # Access internal method for provider
        vcs, provider = analyzer._detect_vcs(tmp_path)
        assert provider == "github"

    def test_detect_gitlab_provider(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = git@gitlab.com:user/repo.git\n',
            encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        vcs, provider = analyzer._detect_vcs(tmp_path)
        assert provider == "gitlab"

    def test_no_vcs(self, tmp_path):
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        assert result.project.vcs is None


class TestCICDDetection:
    """Detect CI/CD systems."""

    def test_github_actions(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        analyzer = ProjectAnalyzer()
        ci = analyzer._detect_ci_cd(tmp_path)
        assert ci == "github_actions"

    def test_gitlab_ci(self, tmp_path):
        (tmp_path / ".gitlab-ci.yml").write_text("stages: [build]", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        ci = analyzer._detect_ci_cd(tmp_path)
        assert ci == "gitlab_ci"

    def test_no_ci(self, tmp_path):
        analyzer = ProjectAnalyzer()
        assert analyzer._detect_ci_cd(tmp_path) is None


class TestServiceDetection:
    """Detect external services from env files."""

    def test_detect_postgres_from_env(self, tmp_path):
        (tmp_path / ".env.example").write_text(
            "DATABASE_URL=postgres://localhost/db\n", encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        services = analyzer._detect_services(tmp_path)
        assert "postgres" in services

    def test_detect_redis_from_env(self, tmp_path):
        (tmp_path / ".env").write_text("REDIS_URL=redis://localhost\n", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        services = analyzer._detect_services(tmp_path)
        assert "redis" in services


class TestDockerDetection:
    """Detect Docker usage."""

    def test_dockerfile_present(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        assert analyzer._detect_docker(tmp_path) is True

    def test_no_docker(self, tmp_path):
        analyzer = ProjectAnalyzer()
        assert analyzer._detect_docker(tmp_path) is False


class TestRecommendations:
    """Context-aware server recommendations."""

    def test_python_project_gets_serena(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        servers = [r.server for r in result.recommendations]
        assert "serena" in servers

    def test_github_project_gets_github_rec(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/u/r.git\n',
            encoding="utf-8",
        )
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        servers = [r.server for r in result.recommendations]
        assert "github" in servers

    def test_deduplication(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project(str(tmp_path))
        server_names = [r.server for r in result.recommendations]
        assert len(server_names) == len(set(server_names))

    def test_nonexistent_directory(self):
        analyzer = ProjectAnalyzer()
        result = analyzer.analyze_project("/nonexistent/path/xxx")
        assert result.recommendations == []


class TestEnvVarMasking:
    """Sensitive env var value masking."""

    def test_mask_api_key(self, tmp_path):
        (tmp_path / ".env").write_text("MY_API_KEY=sk-123456789\n", encoding="utf-8")
        analyzer = ProjectAnalyzer()
        env_vars = analyzer._detect_env_vars(tmp_path)
        assert env_vars.get("MY_API_KEY", "").endswith("****")
        assert not env_vars.get("MY_API_KEY", "").endswith("sk-123456789")
