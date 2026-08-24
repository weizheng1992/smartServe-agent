export interface PersonaRecord {
  id: string;
  userId: string;
  businessId: string;
  fact: string;
  confidence: number;
  source: string;
  status: 'approved' | 'pending' | 'rejected';
  createdAt: string;
}
