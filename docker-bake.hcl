variable "DOCKER_REGISTRY" {
  default = "ghcr.io/bettorld"
}

variable "VERSION" {
  default = "latest"
}

group "default" {
  targets = ["db-backup-orchestrator"]
}

target "db-backup-orchestrator" {
  context    = "."
  dockerfile = "Dockerfile"
  tags = [
    "${DOCKER_REGISTRY}/db-backup-orchestrator:${VERSION}",
    "${DOCKER_REGISTRY}/db-backup-orchestrator:latest",
  ]
  platforms = ["linux/amd64"]
}

target "db-backup-orchestrator-dev" {
  inherits  = ["db-backup-orchestrator"]
  tags      = ["db-backup-orchestrator:dev"]
  platforms = ["linux/amd64"]
  no-cache  = true
}
