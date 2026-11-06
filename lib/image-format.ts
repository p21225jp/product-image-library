// Validate container structure and dimensions independently of browser metadata.
const bad=():never=>{throw Object.assign(new Error('图片格式无效、内容损坏或不是静态图片。'),{status:400});};
export function inspectImage(b:Uint8Array){
  const v=new DataView(b.buffer,b.byteOffset,b.byteLength),str=(p:number,n:number)=>String.fromCharCode(...b.subarray(p,p+n));
  let width=0,height=0,extension='',alphaPossible=false;
  if(b.length>32&&str(1,3)==='PNG'&&b[0]===137&&str(12,4)==='IHDR'){
    extension='png';width=v.getUint32(16);height=v.getUint32(20);alphaPossible=[4,6].includes(b[25]);let end=false,data=false;
    for(let p=8;p+12<=b.length;){const size=v.getUint32(p),kind=str(p+4,4);if(size>b.length-p-12)bad();if(kind==='acTL')bad();if(kind==='tRNS')alphaPossible=true;if(kind==='IDAT')data=true;if(kind==='IEND'){end=true;if(p+12!==b.length)bad();break;}p+=12+size;}
    if(!end||!data)bad();
  }else if(b.length>12&&b[0]===255&&b[1]===216&&b[b.length-2]===255&&b[b.length-1]===217){
    extension='jpg';let found=false;
    for(let p=2;p+4<b.length;){if(b[p]!==255)bad();while(b[p]===255)p++;const marker=b[p++];if(marker===0xda)break;if(marker===0x01||(marker>=0xd0&&marker<=0xd9))continue;const length=v.getUint16(p);if(length<2||p+length>b.length)bad();if([0xc0,0xc1,0xc2].includes(marker)){height=v.getUint16(p+3);width=v.getUint16(p+5);found=true;}p+=length;}if(!found)bad();
  }else if(b.length>20&&str(0,4)==='RIFF'&&str(8,4)==='WEBP'){
    extension='webp';if(v.getUint32(4,true)+8!==b.length)bad();let data=false;
    for(let p=12;p+8<=b.length;){const kind=str(p,4),size=v.getUint32(p+4,true),d=p+8;if(size>b.length-d)bad();if(['ANIM','ANMF'].includes(kind))bad();if(kind==='VP8X'){if(size<10||b[d]&2)bad();alphaPossible=!!(b[d]&16);width=1+b[d+4]+(b[d+5]<<8)+(b[d+6]<<16);height=1+b[d+7]+(b[d+8]<<8)+(b[d+9]<<16);}if(kind==='VP8 '){if(size<10||str(d+3,3)!=='\x9d\x01\x2a')bad();if(!width){width=v.getUint16(d+6,true)&16383;height=v.getUint16(d+8,true)&16383;}data=true;}if(kind==='VP8L'){if(size<5||b[d]!==47)bad();const bits=v.getUint32(d+1,true);if(!width){width=(bits&16383)+1;height=((bits>>>14)&16383)+1;}alphaPossible ||=!!(bits&0x10000000);data=true;}p=d+size+(size%2);}
    if(!data)bad();
  }else bad();
  if(!width||!height||width*height>40000000)bad();return {width,height,extension,alphaPossible,mime:extension==='jpg'?'image/jpeg':`image/${extension}`};
}
