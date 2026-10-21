"""Real Galileo sky over the LS-07 site (Murfeld, AT) for the design canvas.

pip install skyfield numpy && python compute_sky.py   -> writes sky2.json next to this file
"""
import json, math, os, numpy as np, random
HERE = os.path.dirname(os.path.abspath(__file__))
from skyfield.api import load, wgs84, EarthSatellite
ts=load.timescale()
L=[l.rstrip() for l in open(os.path.join(HERE,'galileo.3le'))]
sats=[EarthSatellite(L[i+1],L[i+2],L[i].strip(),ts) for i in range(0,len(L),3)]
site=wgs84.latlon(46.705,15.655,250)
now=ts.utc(2026,10,19,17,0,0); now1=ts.utc(2026,10,19,17,0,1); rec=ts.utc(2026,10,19,11,0,0)
C=299792458;F=1575.42e6
def xy(el,az,R=170,c=200):
  r=R*(90-el)/90;return round(c+r*math.sin(math.radians(az)),1),round(c-r*math.cos(math.radians(az)),1)
def dop(rs):
  G=np.array([[math.cos(math.radians(e))*math.sin(math.radians(a)),math.cos(math.radians(e))*math.cos(math.radians(a)),math.sin(math.radians(e)),1] for e,a in rs]);Q=np.linalg.inv(G.T@G)
  return [round(float(np.sqrt(Q[0,0]+Q[1,1]+Q[2,2])),2),round(float(np.sqrt(Q[0,0]+Q[1,1])),2),round(float(np.sqrt(Q[3,3])),2)]
auth=[];low=[];rep=[]
for s in sats:
  t=(s-site).at(now);a,z,d=t.altaz();d2=(s-site).at(now1).altaz()[2].m
  nm=s.name.split()[0];nick=s.name[s.name.find('(')+1:s.name.find(')')].replace('GALILEO','Galileo').replace('Galileo-','Galileo ')
  e=a.degrees;az=z.degrees
  if e>=10: auth.append(dict(id=nm,nick=nick,el=round(e,1),az=round(az,1),rng=round(d.km),dop=round(-(d2-d.m)/C*F),cn0=round(34+16*math.sin(math.radians(e)),1),xy=xy(e,az)))
  elif e>=0: low.append(dict(id=nm,xy=xy(e,az)))
  ra,rz,_=(s-site).at(rec).altaz()
  if ra.degrees>=10: rep.append(dict(id=nm,rel=round(ra.degrees,1),raz=round(rz.degrees,1),el=round(e,1),az=round(az,1),xy=xy(ra.degrees,rz.degrees)))
auth.sort(key=lambda r:-r['el']);rep.sort(key=lambda r:-r['rel'])
random.seed(7)
for r in rep: r['cn0']=round(47.2+random.uniform(-.35,.35),1)
out=dict(auth=auth,low=low,rep=rep,dop=dop([(r['el'],r['az']) for r in auth]),repdop=dop([(r['rel'],r['raz']) for r in rep]))
json.dump(out,open(os.path.join(HERE,'sky2.json'),'w'))
print('auth',len(auth),out['dop']);[print(r) for r in auth]
print('low',low)
print('rep',len(rep),out['repdop']);[print(r) for r in rep]
