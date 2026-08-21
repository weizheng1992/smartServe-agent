import { type NextRequest, NextResponse } from 'next/server';
import { ImageUploadService } from '../services/imageUploadService';

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const file = (formData.get('file') || formData.get('image')) as File | null;

    const result = await ImageUploadService.uploadImage(file);

    if (!result.success) {
      return NextResponse.json({ success: false, error: result.error }, { status: result.statusCode || 400 });
    }

    return NextResponse.json({
      success: true,
      url: result.url,
      filename: result.filename,
      originalName: result.originalName,
      size: result.size,
      mimeType: result.mimeType,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error handling image upload:', error);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
