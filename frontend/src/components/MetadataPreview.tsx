import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { MetadataJSON, ISASheetData } from '../api/client';

interface Props {
  projectId: string;
  sessionId: string;
}

const ISA_ORDER = ['investigation', 'study', 'assay', 'sample', 'observationunit'];

const METADATA_FILENAMES = ['metadata.json', 'metadata_json.json'];

export default function MetadataPreview({ projectId, sessionId }: Props) {
  const [data, setData] = useState<MetadataJSON | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('investigation');

  useEffect(() => {
    let active = true;
    
    const fetchMetadata = async () => {
      let lastError = '';
      for (const filename of METADATA_FILENAMES) {
        try {
          const url = api.getArtifactUrl(projectId, filename);
          const urlWithSession = url.includes('?') ? `${url}&session=${sessionId}` : `${url}?session=${sessionId}`;
          
          const res = await fetch(urlWithSession);
          if (!res.ok) {
            lastError = `${filename} not available`;
            continue;
          }
          
          const json = await res.json() as MetadataJSON;
          if (active) {
            setData(json);
            setLoading(false);
            const available = ISA_ORDER.find(tab => json.isa_structure?.[tab]);
            if (available) setActiveTab(available);
            return; // Success
          }
        } catch (err: unknown) {
          lastError = err instanceof Error ? err.message : String(err);
        }
      }
      
      if (active) {
        setError(lastError);
        setLoading(false);
      }
    };

    fetchMetadata();
    return () => { active = false; };
  }, [projectId, sessionId]);

  if (loading) return <div className="p-4 text-slate-500 text-sm">Loading metadata preview...</div>;
  if (error || !data?.isa_structure) return null;

  const tabs = ISA_ORDER.filter(tab => data.isa_structure[tab]);
  const currentSheet = data.isa_structure[activeTab] as ISASheetData | undefined;
  
  const renderContent = () => {
    if (!currentSheet) return null;

    // Multi-row view (for samples, assays, etc.)
    if (currentSheet.rows && currentSheet.rows.length > 1 && currentSheet.columns) {
      return (
        <div style={{ overflowX: 'auto', maxHeight: '400px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
            <thead style={{ position: 'sticky', top: 0, background: '#fcfcfd', zIndex: 1 }}>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                {currentSheet.columns.map(col => (
                  <th key={col} style={{ padding: '10px 12px', fontWeight: 600, color: '#475569', whiteSpace: 'nowrap' }}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {currentSheet.rows.map((row, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  {currentSheet.columns!.map(col => {
                    const val = row[col.toLowerCase().replace(/ /g, '_')] || row[col.toLowerCase()] || '';
                    return (
                      <td key={col} style={{ padding: '10px 12px', color: '#334155' }}>
                        {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    // Single entity / fields view
    const fields = currentSheet.fields || [];
    return (
      <div style={{ overflowX: 'auto', maxHeight: '400px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
          <thead style={{ position: 'sticky', top: 0, background: '#fcfcfd', zIndex: 1 }}>
            <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', width: '30%' }}>Field Name</th>
              <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569' }}>Extracted Value</th>
              <th style={{ padding: '12px 16px', fontWeight: 600, color: '#475569', width: '15%' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {fields.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>No fields extracted for this level.</td>
              </tr>
            ) : (
              fields.map((f, i) => {
                const status = f.status || 'confirmed';
                const isProvisional = status.includes('provisional');
                const isUngrounded = status === 'provisional_ungrounded';
                
                const name = f.field_name || 'Unknown';
                const val = typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value || '');
                
                let statusColor = '#10b981'; // confirmed
                if (isUngrounded) statusColor = '#f97316'; // orange for ungrounded
                else if (isProvisional) statusColor = '#f59e0b'; // amber for general provisional
                
                return (
                  <tr key={`${name}-${i}`} style={{ borderBottom: '1px solid #f1f5f9', background: isProvisional ? '#fffbeb' : 'transparent' }}>
                    <td style={{ padding: '12px 16px', color: '#0f172a', fontWeight: 500 }}>
                       <span 
                         title={isUngrounded ? 'Missing source reference' : isProvisional ? 'Provisional' : 'Confirmed'} 
                         style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: statusColor, marginRight: '8px' }}
                       ></span>
                       {name}
                    </td>
                    <td style={{ padding: '12px 16px', color: '#334155', wordBreak: 'break-word' }}>{val}</td>
                    <td style={{ padding: '12px 16px', color: statusColor, fontSize: '11px', fontWeight: 600, textTransform: 'uppercase' }}>
                       {isUngrounded ? 'No Source' : status}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="metadata-preview-container" style={{ background: 'white', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden', marginBottom: '24px' }}>
      <div style={{ padding: '16px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <p style={{ margin: 0, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px', color: '#64748b', fontWeight: 600 }}>Data Extraction</p>
          <h2 style={{ margin: '4px 0 0 0', fontSize: '16px', fontWeight: 600, color: '#0f172a' }}>Metadata Preview</h2>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
           <span style={{ fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#64748b' }}><span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }}></span> Confirmed</span>
           <span style={{ fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#64748b' }}><span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#f59e0b' }}></span> Provisional</span>
           <span style={{ fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#64748b' }}><span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#f97316' }}></span> No Source</span>
        </div>
      </div>
      
      <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', background: '#f8fafc', padding: '0 8px', overflowX: 'auto' }}>
        {tabs.map(tab => (
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
              textTransform: 'capitalize'
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {renderContent()}
    </div>
  );
}
