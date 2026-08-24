export interface EvalRunRecord {
  id: string;
  runName: string;
  datasetName: string;
  sampleCount: number;
  toolAccuracy: number;
  ragFaithfulness: number;
  hitlTriggerRate: number;
  status: 'completed' | 'running' | 'failed';
  createdAt: string;
}
