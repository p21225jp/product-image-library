// Streaming ZIP_STORED writer. Holds only per-entry headers and one file chunk.
const encoder=new TextEncoder();
const table=Uint32Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
function crc(crc:number,data:Uint8Array){for(const byte of data)crc=table[(crc^byte)&255]^(crc>>>8);return crc;}
function bytes(size:number,write:(v:DataView)=>void){const b=new Uint8Array(size);write(new DataView(b.buffer));return b;}
type Entry={object:{body:ReadableStream<Uint8Array>;size:number};name:string};
export function zipStream(entries:Entry[]){
  async function* generate(){
    let offset=0;const central:Uint8Array[]=[];
    for(const {object,name} of entries){
      const filename=encoder.encode(name),start=offset;
      const header=bytes(30,v=>{v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x0808,true);v.setUint16(26,filename.length,true);});
      yield header;yield filename;offset+=header.length+filename.length;
      const reader=object.body.getReader();let checksum=0xffffffff,size=0;
      try{while(true){const {value,done}=await reader.read();if(done)break;checksum=crc(checksum,value);size+=value.length;offset+=value.length;yield value;}}finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
      if(size!==object.size)throw new Error('原图传输长度不完整。');checksum=(checksum^0xffffffff)>>>0;
      const descriptor=bytes(16,v=>{v.setUint32(0,0x08074b50,true);v.setUint32(4,checksum,true);v.setUint32(8,size,true);v.setUint32(12,size,true);});yield descriptor;offset+=16;
      const directory=bytes(46+filename.length,v=>{v.setUint32(0,0x02014b50,true);v.setUint16(4,20,true);v.setUint16(6,20,true);v.setUint16(8,0x0808,true);v.setUint32(16,checksum,true);v.setUint32(20,size,true);v.setUint32(24,size,true);v.setUint16(28,filename.length,true);v.setUint32(42,start,true);});directory.set(filename,46);central.push(directory);
    }
    const start=offset;for(const directory of central){yield directory;offset+=directory.length;}
    yield bytes(22,v=>{v.setUint32(0,0x06054b50,true);v.setUint16(8,entries.length,true);v.setUint16(10,entries.length,true);v.setUint32(12,offset-start,true);v.setUint32(16,start,true);});
  }
  const iterator=generate();return new ReadableStream<Uint8Array>({async pull(controller){try{const r=await iterator.next();if(r.done)controller.close();else controller.enqueue(r.value);}catch(e){controller.error(e);await iterator.return(undefined);}},async cancel(){await iterator.return(undefined);}});
}
