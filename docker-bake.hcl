variable "DOCKER_REGISTRY" {
  default = "docker.io"
}

variable "VERSION" {
  default = "production"
}

group "default" {
  targets = ["db-backup-orchestrator"]
}

target "db-backup-orchestrator" {
  context    = "."
  dockerfile = "Dockerfile"
  tags = [
    "${DOCKER_REGISTRY}/db-backup-orchestrator:${VERSION}",
    "${DOCKER_REGISTRY}/db-backup-orchestrator:production",
  ]
  platforms = ["linux/amd64"]
}

target "db-backup-orchestrator-dev" {
  inherits  = ["db-backup-orchestrator"]
  tags      = ["db-backup-orchestrator:dev"]
  platforms = ["linux/amd64"]
  no-cache  = true
}
