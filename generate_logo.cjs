// Script para gerar logo.png a partir do logo-icon.svg com fundo transparente
// Usa puppeteer (headless Chrome) para renderizar SVG → PNG com transparência

async function generatePNG() {
  const fs = await import('node:fs');
  const path = await import('node:path');
  let puppeteer;
  try {
    puppeteer = await import('puppeteer');
  } catch {
    console.log('Puppeteer não instalado. Usando método alternativo com sharp...');
    try {
      const sharp = (await import('sharp')).default;
      const svgPath = path.join(__dirname, 'public', 'logo-icon.svg');
      const pngPath = path.join(__dirname, 'public', 'logo.png');
      const svgBuffer = fs.readFileSync(svgPath);
      
      await sharp(svgBuffer)
        .resize(512, 512)
        .png()
        .toFile(pngPath);
      
      console.log('✅ logo.png gerado com sharp:', pngPath);
      return;
    } catch {
      console.log('Sharp também não disponível. Tentando com canvas...');
    }
    
    // Fallback: criar um HTML que pode ser aberto manualmente
    const svgContent = fs.readFileSync(path.join(__dirname, 'public', 'logo-icon.svg'), 'utf8');
    const html = `<!DOCTYPE html>
<html>
<head><title>Logo PNG Generator</title></head>
<body style="margin:0;background:transparent;">
  <canvas id="c" width="512" height="512"></canvas>
  <script>
    const img = new Image();
    const svg = \`${svgContent.replace(/`/g, '\\`')}\`;
    const blob = new Blob([svg], {type: 'image/svg+xml'});
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      const c = document.getElementById('c');
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0, 512, 512);
      const link = document.createElement('a');
      link.download = 'logo.png';
      link.href = c.toDataURL('image/png');
      link.click();
      document.body.innerHTML = '<h2 style="color:green;font-family:sans-serif;text-align:center;margin-top:40px">✅ Logo PNG downloaded! Copy it to public/logo.png</h2>';
    };
    img.src = url;
  </script>
</body>
</html>`;
    fs.writeFileSync(path.join(__dirname, 'generate_logo_page.html'), html);
    console.log('⚠️  Abra generate_logo_page.html no navegador para baixar o PNG.');
    return;
  }

  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  
  const svgContent = fs.readFileSync(path.join(__dirname, 'public', 'logo-icon.svg'), 'utf8');
  
  await page.setContent(`
    <html>
    <body style="margin:0;padding:0;background:transparent;">
      <div id="logo" style="width:512px;height:512px;">
        ${svgContent}
      </div>
    </body>
    </html>
  `);
  
  await page.setViewport({ width: 512, height: 512 });
  
  const element = await page.$('#logo');
  await element.screenshot({
    path: path.join(__dirname, 'public', 'logo.png'),
    omitBackground: true,
  });
  
  await browser.close();
  console.log('✅ logo.png gerado com puppeteer!');
}

generatePNG().catch(console.error);
