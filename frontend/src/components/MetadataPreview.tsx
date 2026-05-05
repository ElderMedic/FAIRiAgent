import { useEffect, useState } from 'react';
import { api, type ISASheetData, type MetadataFieldPreview, type MetadataJSON } from '../api/client';
import { ISA_ORDER } from '../constants/isaOrder';
import type { WebSession } from '../utils/session';

interface Props {
  projectId: string;
  session: WebSession;
}

const MATRIX_ARTIFACTS = ['isa_values_json.json'] as const;
const METADATA_ARTIFACTS = ['metadata.json', 'metadata_json.json'] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function normalizeFieldKey(value: string): string {
  return value.trim().toLowerCase();
}

function coerceMetadataJson(payload: unknown): MetadataJSON | null {
  if (!isRecord(payload)) return null;

  if (isRecord(payload.isa_structure)) {
    return payload as MetadataJSON;
  }

  const looksLikeSheetMap = ISA_ORDER.some((sheet) => isRecord(payload[sheet]));
  if (!looksLikeSheetMap) return null;

  return {
    isa_structure: payload as Record<string, ISASheetData>,
  };
}

function hasSheetContent(sheet: ISASheetData | undefined): boolean {
  if (!sheet) return false;
  return (sheet.rows?.length ?? 0) > 0 || (sheet.fields?.length ?? 0) > 0;
}

function mergeSheetData(
  matrixSheet: ISASheetData | undefined,
  metadataSheet: ISASheetData | undefined,
): ISASheetData | undefined {
  if (!matrixSheet && !metadataSheet) return undefined;

  return {
    description: metadataSheet?.description ?? matrixSheet?.description,
    columns: matrixSheet?.columns ?? metadataSheet?.columns,
    rows: matrixSheet?.rows ?? metadataSheet?.rows,
    fields: metadataSheet?.fields ?? matrixSheet?.fields,
  };
}

function mergePreviewSources(
  matrixData: MetadataJSON | null,
  metadataData: MetadataJSON | null,
): MetadataJSON | null {
  if (!matrixData && !metadataData) return null;

  const mergedStructure: Record<string, ISASheetData> = {};
  for (const sheet of ISA_ORDER) {
    const mergedSheet = mergeSheetData(
      matrixData?.isa_structure?.[sheet],
      metadataData?.isa_structure?.[sheet],
    );
    if (mergedSheet && hasSheetContent(mergedSheet)) {
      mergedStructure[sheet] = mergedSheet;
    }
  }

  if (!Object.keys(mergedStructure).length) return null;

  return {
    ...(metadataData ?? matrixData ?? {}),
    isa_structure: mergedStructure,
  };
}

async function fetchFirstAvailableArtifact(
  projectId: string,
  session: WebSession,
  candidates: readonly string[],
): Promise<MetadataJSON | null> {
  for (const name of candidates) {
    try {
      const response = await fetch(api.getArtifactUrl(projectId, name, session));
      if (!response.ok) continue;
      const payload: unknown = await response.json();
      const parsed = coerceMetadataJson(payload);
      if (parsed) return parsed;
    } catch {
      // Try the next candidate.
    }
  }
  return null;
}

function fieldStatusMap(fields: MetadataFieldPreview[] | undefined): Map<string, MetadataFieldPreview> {
  const map = new Map<string, MetadataFieldPreview>();
  for (const field of fields ?? []) {
    map.set(normalizeFieldKey(field.field_name), field);
  }
  return map;
}

function inferColumns(rows: Record<string, unknown>[] | undefined): string[] {
  if (!rows?.length) return [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      seen.add(key);
    }
  }
  return [...seen];
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function statusColor(status: string | undefined): string {
  if (status?.includes('provisional')) return '#f59e0b';
  if (status?.includes('confirmed')) return '#10b981';
  return '#94a3b8';
}

function statusLabel(field: MetadataFieldPreview | undefined): string {
  if (!field?.status) return 'Status unavailable';
  if (field.status_reason === 'missing_source_reference') {
    return 'Provisional: missing source reference';
  }
  if (field.status_reason === 'low_extraction_confidence') {
    return 'Provisional: low extraction confidence';
  }
  return field.status;
}

function statusHint(field: MetadataFieldPreview | undefined): string {
  if (!field?.status) return 'No provenance status is available for this field.';
  if (field.status_reason === 'missing_source_reference') {
    return 'The value was extracted, but the agent could not attach a source reference packet.';
  }
  if (field.status_reason === 'low_extraction_confidence') {
    return 'The extracted value is tentative because the model confidence was below the confirmation threshold.';
  }
  return 'The extracted value met the current confirmation and provenance checks.';
}

export default function MetadataPreview({ projectId, session }: Props) {
  const [data, setData] = useState<MetadataJSON | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<string>('investigation');

  useEffect(() => {
    let active = true;

    Promise.all([
      fetchFirstAvailableArtifact(projectId, session, MATRIX_ARTIFACTS),
      fetchFirstAvailableArtifact(projectId, session, METADATA_ARTIFACTS),
    ])
      .then(([matrixData, metadataData]) => {
        if (!active) return;
        const merged = mergePreviewSources(matrixData, metadataData);
        setData(merged);
        const available = ISA_ORDER.find((sheet) => hasSheetContent(merged?.isa_structure?.[sheet]));
        if (available) setActiveTab(available);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [projectId, session]);

  if (loading) {
    return <div className="p-4 text-slate-500 text-sm">Loading metadata preview...</div>;
  }
  if (!data?.isa_structure) return null;

  const tabs = ISA_ORDER.filter((sheet) => hasSheetContent(data.isa_structure[sheet]));
  if (!tabs.length) return null;

  const currentSheet = data.isa_structure[activeTab];
  const rows = currentSheet?.rows ?? [];
  const columns = currentSheet?.columns?.length ? currentSheet.columns : inferColumns(rows);
  const fields = currentSheet?.fields ?? [];
  const statusByField = fieldStatusMap(fields);
  const hasMatrixView = rows.length > 0 && columns.length > 0;

  return (
    <div style={{ background: 'white', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden', marginBottom: '24px' }}>
      <div style={{ padding: '16px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <p style={{ margin: 0, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#64748b', fontWeight: 600 }}>Data Extraction</p>
          <h2 style={{ margin: '4px 0 0 0', fontSize: '16px', fontWeight: 600, color: '#0f172a' }}>Metadata Preview</h2>
          <p style={{ margin: '6px 0 0 0', fontSize: '13px', color: '#64748b' }}>
            Preview extracted ISA content directly in the browser. Provisional fields still need curator review.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span style={{ fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#64748b' }}>
            <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
            Confirmed
          </span>
          <span style={{ fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#64748b' }}>
            <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#f59e0b' }} />
            Provisional
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', background: '#f8fafc', padding: '0 8px', overflowX: 'auto' }}>
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            style={{
              border: 'none',
              borderBottom: activeTab === tab ? '2px solid #3b82f6' : '2px solid transparent',
              background: 'transparent',
              padding: '12px 16px',
              fontSize: '13px',
              fontWeight: activeTab === tab ? 600 : 500,
              color: activeTab === tab ? '#3b82f6' : '#64748b',
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      <div style={{ overflowX: 'auto', maxHeight: '420px' }}>
        {hasMatrixView ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#fcfcfd', zIndex: 1 }}>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', width: '72px' }}>Row</th>
                {columns.map((column) => {
                  const fieldMeta = statusByField.get(normalizeFieldKey(column));
                  const fieldStatus = fieldMeta?.status;
                  return (
                    <th key={column} style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', minWidth: '180px', verticalAlign: 'bottom' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span
                          title={`${statusLabel(fieldMeta)}. ${statusHint(fieldMeta)}`}
                          style={{
                            display: 'inline-block',
                            width: '8px',
                            height: '8px',
                            borderRadius: '50%',
                            background: statusColor(fieldStatus),
                            flexShrink: 0,
                          }}
                        />
                        <span>{column}</span>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`row-${index}`} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '12px 16px', color: '#64748b', fontWeight: 600 }}>{index + 1}</td>
                  {columns.map((column) => {
                    const fieldStatus = statusByField.get(normalizeFieldKey(column))?.status;
                    return (
                      <td
                        key={`${index}-${column}`}
                        style={{
                          padding: '12px 16px',
                          color: '#334155',
                          wordBreak: 'break-word',
                          background: fieldStatus?.includes('provisional') ? '#fffbeb' : 'transparent',
                        }}
                      >
                        {formatCellValue(row[column])}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#fcfcfd', zIndex: 1 }}>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', width: '30%' }}>Field Name</th>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569' }}>Extracted Value</th>
                <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', width: '12%' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {fields.length === 0 ? (
                <tr>
                  <td colSpan={3} style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>No fields extracted for this level.</td>
                </tr>
              ) : (
                fields.map((field, index) => {
                  const isProvisional = field.status?.includes('provisional');
                  const label = statusLabel(field);
                  return (
                    <tr key={`${field.field_name}-${index}`} style={{ borderBottom: '1px solid #f1f5f9', background: isProvisional ? '#fffbeb' : 'transparent' }}>
                      <td style={{ padding: '12px 16px', color: '#0f172a', fontWeight: 500 }}>
                        <span
                          title={`${label}. ${statusHint(field)}`}
                          style={{
                            display: 'inline-block',
                            width: '8px',
                            height: '8px',
                            borderRadius: '50%',
                            background: statusColor(field.status),
                            marginRight: '8px',
                          }}
                        />
                        {field.field_name}
                      </td>
                      <td style={{ padding: '12px 16px', color: '#334155', wordBreak: 'break-word' }}>
                        {formatCellValue(field.value)}
                      </td>
                      <td style={{ padding: '12px 16px', color: isProvisional ? '#f59e0b' : '#10b981' }}>
                        {label}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
