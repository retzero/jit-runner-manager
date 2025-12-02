{{/*
Expand the name of the chart.
*/}}
{{- define "jit-runner-manager.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "jit-runner-manager.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "jit-runner-manager.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "jit-runner-manager.labels" -}}
helm.sh/chart: {{ include "jit-runner-manager.chart" . }}
{{ include "jit-runner-manager.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "jit-runner-manager.selectorLabels" -}}
app.kubernetes.io/name: {{ include "jit-runner-manager.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "jit-runner-manager.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "jit-runner-manager.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Redis URL
*/}}
{{- define "jit-runner-manager.redisUrl" -}}
{{- if .Values.externalRedis.enabled }}
{{- .Values.externalRedis.url }}
{{- else if .Values.redis.enabled }}
{{- printf "redis://%s-redis-master:6379/0" .Release.Name }}
{{- else }}
{{- fail "Redis must be enabled (redis.enabled) or external Redis must be configured (externalRedis.enabled)" }}
{{- end }}
{{- end }}

{{/*
Celery Broker URL
*/}}
{{- define "jit-runner-manager.celeryBrokerUrl" -}}
{{- if .Values.externalRedis.enabled }}
{{- printf "%s" .Values.externalRedis.url | replace "/0" "/1" }}
{{- else if .Values.redis.enabled }}
{{- printf "redis://%s-redis-master:6379/1" .Release.Name }}
{{- else }}
{{- fail "Redis must be enabled for Celery broker" }}
{{- end }}
{{- end }}

{{/*
Celery Result Backend URL
*/}}
{{- define "jit-runner-manager.celeryResultBackend" -}}
{{- if .Values.externalRedis.enabled }}
{{- printf "%s" .Values.externalRedis.url | replace "/0" "/2" }}
{{- else if .Values.redis.enabled }}
{{- printf "redis://%s-redis-master:6379/2" .Release.Name }}
{{- else }}
{{- fail "Redis must be enabled for Celery result backend" }}
{{- end }}
{{- end }}

