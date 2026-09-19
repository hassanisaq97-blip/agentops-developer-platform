variable "project_name" {
  description = "Kort navn brugt som præfiks for alle ressourcer."
  type        = string
  default     = "agentops"
}

variable "environment" {
  description = "Miljønavn (fx dev/staging/prod) — indgår i ressourcenavne."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure-region."
  type        = string
  default     = "westeurope"
}

variable "postgres_admin_username" {
  description = "Admin-brugernavn til Azure Database for PostgreSQL Flexible Server."
  type        = string
  default     = "agentopsadmin"
}

variable "postgres_admin_password" {
  description = "Admin-adgangskode til PostgreSQL. Angives ALDRIG i kildekoden — sæt via TF_VAR_postgres_admin_password eller en .tfvars-fil, der ikke committes."
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API-nøgle. Tomt er gyldigt — platformen falder da tilbage til den deterministiske test-provider."
  type        = string
  sensitive   = true
  default     = ""
}

variable "openai_api_key" {
  description = "OpenAI API-nøgle. Tomt er gyldigt."
  type        = string
  sensitive   = true
  default     = ""
}

variable "api_image" {
  description = "Fuldt image-reference (registry/repo:tag) for API-containeren."
  type        = string
  default     = "" # udfyldes efter `docker push` til det oprettede Container Registry
}

variable "mlflow_image" {
  description = "Fuldt image-reference for MLflow-containeren."
  type        = string
  default     = ""
}
