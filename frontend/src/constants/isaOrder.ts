export const ISA_ORDER = [
  'investigation',
  'study',
  'observationunit',
  'sample',
  'assay',
] as const;

export const ISA_LABELS: Record<string, string> = {
  investigation: 'Investigation',
  study: 'Study',
  observationunit: 'ObservationUnit',
  sample: 'Sample',
  assay: 'Assay',
};
