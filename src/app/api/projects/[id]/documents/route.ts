import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { projectDocuments } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

// Como não há pdf-parse ativo ainda garantidamente, extrairemos usando a API basica de buffer ou Gemini nativamente
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;

    if (!file) {
      return NextResponse.json({ error: "Nenhum arquivo enviado" }, { status: 400 });
    }

    const buffer = await file.arrayBuffer();
    let textContent = "";

    // Para MVP, vamos ler como texto UTF-8 (útil para TXT/CSV e extração simples)
    if (file.name.endsWith(".txt") || file.name.endsWith(".csv") || file.name.endsWith(".md")) {
      textContent = new TextDecoder().decode(buffer);
    } else if (file.name.endsWith(".pdf")) {
      try {
        const { PDFParse } = await import("pdf-parse");
        const parser = new PDFParse({ data: Buffer.from(buffer) });
        const pdfData = await parser.getText();
        textContent = pdfData.text;
      } catch (e) {
         console.error("Erro no pdf-parse:", e);
         // Fallback básico caso pdf-parse não consiga
         textContent = new TextDecoder().decode(buffer).substring(0, 5000) + "... (extração parcial)";
      }
    } else {
       return NextResponse.json({ error: "Formato não suportado ainda." }, { status: 400 });
    }

    // Salvar no BD
    const [doc] = await db.insert(projectDocuments).values({
      projectId: id,
      fileName: file.name,
      content: textContent,
    }).returning();

    return NextResponse.json({ success: true, doc });

  } catch (error) {
    console.error("Erro no upload de documento:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  try {
    const docs = await db.query.projectDocuments.findMany({
      where: eq(projectDocuments.projectId, id),
      orderBy: (docs, { desc }) => [desc(docs.createdAt)],
    });
    
    return NextResponse.json(docs);
  } catch (error) {
    console.error("Erro ao listar documentos:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
