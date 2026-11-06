'use strict';
async function prepareCloudUpload(form, file) {
  const bitmap = await createImageBitmap(file, {imageOrientation:'from-image'});
  try {
    if(bitmap.width*bitmap.height>40000000)throw new Error('图片不能超过 4000 万像素。');
    const canvas=document.createElement('canvas');canvas.width=bitmap.width;canvas.height=bitmap.height;
    const context=canvas.getContext('2d',{willReadFrequently:true});context.drawImage(bitmap,0,0);
    let alpha=false;
    // Scan in strips, keeping temporary pixel memory bounded for large images.
    for(let y=0;y<canvas.height&&!alpha;y+=32){const pixels=context.getImageData(0,y,canvas.width,Math.min(32,canvas.height-y)).data;for(let i=3;i<pixels.length;i+=4)if(pixels[i]<255){alpha=true;break;}}
    if(form.get('background')==='透明'&&!alpha)throw new Error('此文件没有透明像素。请改选「其他」背景。');
    const thumb=document.createElement('canvas');const ratio=Math.min(1,720/bitmap.width,720/bitmap.height);
    thumb.width=Math.max(1,Math.round(bitmap.width*ratio));thumb.height=Math.max(1,Math.round(bitmap.height*ratio));thumb.getContext('2d').drawImage(bitmap,0,0,thumb.width,thumb.height);
    const blob=await new Promise(resolve=>thumb.toBlob(resolve,'image/webp',.85));
    if(!blob)throw new Error('无法生成预览，请换一张图片。');
    form.append('thumbnail',blob,'thumbnail.webp');form.append('display_width',String(bitmap.width));form.append('display_height',String(bitmap.height));form.append('has_alpha',String(alpha));
  } finally {bitmap.close();}
}
