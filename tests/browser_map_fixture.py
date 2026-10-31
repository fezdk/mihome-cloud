import base64,json,zlib
from pathlib import Path
from mihome_cloud import build_map_snapshot
from mihome_cloud.map_view import write_map_view
w,h=100,76
cells=bytearray(w*h)
for y in range(5,71):
 for x in range(5,95):
  cells[y*w+x]=255 if x in (5,94) or y in (5,70) else (3 if x<55 else 4)
points=[]
for row in range(12,60,5):
 xs=range(12,48,3) if (row//5)%2==0 else reversed(range(12,48,3))
 points.extend({'x':x*50,'y':row*50,'type':1} for x in xs)
points.extend({'x':x*50,'y':2700,'type':0} for x in range(48,80,2))
d={'map_id':7,'width':w,'height':h,'resolution':50,'origin_x':0,'origin_y':0,
   'map_data':base64.b64encode(zlib.compress(cells)).decode(),
   'map_room_info':[{'grid_id':3,'room_id':11},{'grid_id':4,'room_id':12}],
   'room_attrs':[{'id':11,'room_name':'Teststue','name_pos_x':1500,'name_pos_y':1800},
                 {'id':12,'room_name':'Testkøkken','name_pos_x':3700,'name_pos_y':1800}],
   'have_pile':True,'pile_x':800,'pile_y':600,'pile_yaw':0,
   'position':{'x':3900,'y':2700,'yaw':0},'paths':{'pose_id':4,'points':points},'task_id':5}
Path('/tmp/mihome-browser-fixture.json').write_text(json.dumps(d))
write_map_view(build_map_snapshot(d,name='Syntetisk testkort'),'/tmp/mihome-browser-fixture')
print('Synthetic browser fixture ready.')
