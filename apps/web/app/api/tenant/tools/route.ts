import { getTenant, getTenantTools, saveTenantTool } from 'db';
import { type NextRequest, NextResponse } from 'next/server';
import { encryptSecret } from 'tools';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const businessId = searchParams.get('businessId') || 'ecommerce';

    const tenant = await getTenant(businessId);
    if (!tenant) {
      return NextResponse.json({ success: true, tools: [] });
    }

    const tools = await getTenantTools(tenant.id);
    return NextResponse.json({
      success: true,
      tools: tools.map((t) => ({
        id: t.id,
        name: t.name,
        description: t.description,
        schema: t.schema,
        authType: t.authType,
        requiresApproval: t.requiresApproval,
        enabled: t.enabled,
        createdAt: t.createdAt,
      })),
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error fetching tenant tools:', error);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      businessId,
      name,
      description,
      schema,
      authType = 'none',
      credentials,
      requiresApproval = false,
      enabled = true,
    } = body;

    if (!businessId || !name || !schema) {
      return NextResponse.json({ success: false, error: 'businessId, name and schema are required' }, { status: 400 });
    }

    const tenant = await getTenant(businessId);
    if (!tenant) {
      return NextResponse.json({ success: false, error: `Tenant ${businessId} not found` }, { status: 404 });
    }

    let encryptedCredentials: string | undefined;
    if (credentials && authType !== 'none') {
      encryptedCredentials = encryptSecret(credentials, process.env.ENCRYPTION_MASTER_KEY, businessId);
    }

    const created = await saveTenantTool({
      tenantId: tenant.id,
      name: name.trim(),
      description: description?.trim(),
      schema,
      authType,
      encryptedCredentials,
      requiresApproval,
      enabled,
    });

    return NextResponse.json({
      success: true,
      tool: {
        id: created.id,
        name: created.name,
        description: created.description,
        schema: created.schema,
        authType: created.authType,
        requiresApproval: created.requiresApproval,
        enabled: created.enabled,
      },
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error saving tenant tool:', error);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
