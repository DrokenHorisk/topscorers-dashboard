{{- define "topscorers.name" -}}
topscorers
{{- end -}}

{{- define "topscorers.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "topscorers.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "topscorers.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
