import datetime
import time
import sys, os
from os import remove

sismos={}
numeventos_update=0
numeventos_exclu=0
archivo=open("select.out", 'r', encoding='latin-1')
newcollect=open("newcollect.txt", "w")
excluidostmp1=open("excluidostmp1.txt", "w")
cabeceras=open("cabeceras.txt", "w")
lineacollect=''
lineacollect_aux=''
tienerms=''
for linea in archivo:
    #print(linea)
    datoslinea=linea.split()
    #print(datoslinea)
    largo=len(datoslinea)
    if len(datoslinea)>0:
        #print('entro')
        cadena='OTH'
        if cadena in datoslinea:
            estaOTH='s'
        else:
            estaOTH='n'

        comienzo = linea[:5]
        #print('paso')
        # devuelve True si la linea no comienza con letras (me sirve saber si comienza con año)
        letras = any(caracter.isalpha() for caracter in comienzo)

        if letras:
            tieneletras='s'
        else:
            tieneletras='n'

        if ((datoslinea[largo-1]=='1' or datoslinea[largo-1][-1:]=='1')) and estaOTH=='n' and tieneletras == 'n': # aca agregar condicion de que en la linea no este OTH
            
            rms=linea[52:56]
            
            if rms.isspace():
                tienerms='n'
            else:
                tienerms='s'

            #print('rms', rms)
            
            #if ((datoslinea[largo-2].find('GUC')!=-1) or (datoslinea[largo-3].find('GUC')!=-1)):
            #if (((datoslinea[largo-2].find('GUC')!=-1) or (datoslinea[largo-3].find('GUC')!=-1))) and largo > 10:
            vecesGUCCSN=0
            tienemag='n'
            vecescoord=0
            for x in datoslinea:
                if x.find('GUC')!=-1 or x.find('CSN')!=-1:
                    vecesGUCCSN=vecesGUCCSN+1
                    if x.find('LGUC')!=-1 or x.find('SGUC')!=-1 or x.find('WGUC')!=-1 or x.find('LCSN')!=-1 or x.find('SCSN')!=-1 or x.find('WCSN')!=-1:
                                tienemag='s'
            for i in datoslinea:
                if i.find('-')!=-1:
                    vecescoord=vecescoord+1

            # condicional que analiza si la linea tipo 1 tiene al menos 2 veces GUC, si tiene alguna magnitud y si tiene las 2 coordenadas (latitud y longitu)
            # estas ultimas que comienzan con "-"
            if vecesGUCCSN >= 2 and tienemag == 's' and vecescoord == 2 and tienerms == 's':
                #time.sleep(30)
                # guarda en txt la linea cabecera
                cabeceras.write(linea)
                orden=0
                for concatena in datoslinea:
                    if (concatena!='L' and concatena!='LE') and (concatena!='R' and concatena!='RE') and concatena!='D':
                        if (concatena.find('LE')!=-1) or (concatena.find('RE')!=-1):
                            # si es verdadero el evento es una explosión
                            if len(concatena) >= 9:
                                if len(concatena)==9:
                                    # evento sin estructura, se le asigna estructura 0 por defecto
                                    # se puede mostrar o guardar el evento en otro txt si se necesita
                                    numextrae=(len(lineacollect)-len(datoslinea[3]))+3
                                    extrae=lineacollect[0:numextrae]
                                    concatena='0'+concatena
                                    newlineacollect=concatena[0:3]+' '+concatena[-7:]
                                    lineacollect=extrae
                                else:    
                                    newlineacollect=concatena[0:7]+' '+concatena[-7:]
                                lineacollect=lineacollect+newlineacollect+' '
    
                        else:
                            separa=lineacollect.split()
                            # si latitud o longitud en grados es mayor a 2 digitos separa coordenadas e incerta un espacio entre ellas
                            if len(separa)>0:
                                analiza=separa[len(separa)-1]
                                num_guion = analiza.count('-')
                                if num_guion == 2:
                                    #pos_guion_1=concatena.find('-')
                                    pos=0
                                    for recorre in analiza:
                                        if recorre=='-' and pos==0:
                                            pos_guion_1=pos
                                            pos=pos+1
                                        else:
                                            if recorre=='-' and pos>0:
                                                pos_guion_2=pos
                                            else:
                                                pos=pos+1

                                    latitud=analiza[pos_guion_1:pos_guion_2]
                                    longitud=analiza[pos_guion_2:]
                                    coordenadas=latitud+' '+longitud
                                    lineacollect=''
                                    for i in range(len(separa)-1):
                                        lineacollect=lineacollect+separa[i]+' '
                                    lineacollect=lineacollect+coordenadas+' '
                            # fin
                            lineacollect=lineacollect+concatena+' '
                    else:
                        lineacollect=lineacollect+concatena+' '
                
                #numeventos+=1

            else:
                
                posicion=1
                contiene=''
                if any(c.isalpha() for c in datoslinea[0]):
                    contiene="s" # la cadena contiene al menos una letra del abecedario (er para determinar si es una linea de tipo 1 ya que esta solo tiene numeros que corresponde al año
                else:
                    contiene="n" # la cadena NO contiene letras del abecedario
                
                # pregunta si la linea analizada es una linea del tipo "1" y no una linea que tenga que ver con una una estacion   
                if len(datoslinea[largo-1]) == 1 and contiene=="n":
                    contiene=''
                    new_datoslinea=[]
                    pos=0
                    indice = -1

                    #posicion_o = datoslinea.find("L") or datoslinea.find("R") or datoslinea.find("D")
                    
                    for indicefind, elemento in enumerate(datoslinea):
                        letraL="L" # hacer lo mismo para letras L R D para saber en que posicion estan
                        letraR="R"
                        letraD="D"

                        # determina el indice dentro de la lista donde esta definido si es un evento local, regional o distante
                        if letraL in elemento:
                            indice = indicefind
                            break # Detiene el bucle tan pronto como encuentra el primer elemento

                        if letraR in elemento:
                            indice = indicefind
                            break # Detiene el bucle tan pronto como encuentra el primer elemento

                        if letraD in elemento:
                            indice = indicefind
                            break # Detiene el bucle tan pronto como encuentra el primer elemento

                    for elemento in datoslinea:
                        if pos == indice-1:
                            if len(datoslinea[indice]) == 1:
                                new_datoslinea.append(elemento+datoslinea[pos+1])
                            else:
                                new_datoslinea.append(elemento)
                                new_datoslinea.append(datoslinea[indice])
                        else:
                            if pos < indice or pos > indice:
                                new_datoslinea.append(elemento)
                                
                        pos=pos+1

                    # se agregan los ceros antes en mes/dia/hora/minuto
                    linea_aux=''
                    posicion=1
                    
                    for dato in new_datoslinea:
                        # solo entrara si el contenido de i tiene solo 1 digito y hasta la posicion 3 de la lista
                        
                        # pone siempre cero antes
                        if len(dato) == 1 and posicion <= 5:
                            linea_aux=linea_aux + '0'+ dato + ' '
                        else:
                            if len(dato) == 3 and posicion <= 4:
                                linea_aux=linea_aux + '0'+ dato + ' '
                            else:
                                linea_aux=linea_aux + dato + ' '
                        lineacollect_aux=linea_aux
                        posicion=posicion+1

            #time.sleep(30)

        # si el if es verdadero se guarda evento en nuevo collect o en excluidos
        if datoslinea[largo-1]=='I':
            estado=datoslinea[0][7:]
            #if datoslinea[0].find('UP')!=-1:
            if estado=='UP':
                update='s'
            else:
                update='n'

            # si el if es verdadero se guarda en nuevo collect

            # si el if es verdadero el evento se guarda en nuevo collect
            #if len(lineacollect_aux) == 0 and (vecesGUC == 2 and tienemag == 's' and vecescoord == 2 and update=='s' and tienerms =='s'):
            if len(lineacollect_aux) == 0 and (vecesGUCCSN == 2 and tienemag == 's' and vecescoord == 2 and tienerms =='s'):    
                lineacollect+=datoslinea[3][3:]
                newcollect.write(lineacollect+"\n")
                numeventos_update+=1
                #eventorms=''
            else:
                # de lo contrario se guarda en excluidos
                # los eventos excluidos son 
                # sin la agencia (2 o mas veces) / sin magnitud / sin coordenadas / sin rms

                #print(datoslinea)
                #print(lineacollect)

                if len(lineacollect_aux)==0:
                    new_datoslinea=lineacollect.split()
                    # se agregan los ceros antes en mes/dia/hora/minuto
                    linea_aux=''
                    posicion=1
                    
                    for dato in new_datoslinea:
                        # solo entrara si el contenido de i tiene solo 1 digito y hasta la posicion 3 de la lista
                        # pone siempre cero antes
                        if len(dato) == 1 and posicion <= 5:
                            linea_aux=linea_aux + '0'+ dato + ' '
                        else:
                            if len(dato) == 3 and posicion <= 4:
                                linea_aux=linea_aux + '0'+ dato + ' '
                            else:
                                linea_aux=linea_aux + dato + ' '
                        lineacollect_aux=linea_aux
                        posicion=posicion+1

                    lineacollect_aux=lineacollect_aux+datoslinea[3][3:]

                else:
                    lineacollect_aux+=datoslinea[3][3:]
                
                excluidostmp1.write(lineacollect_aux+"\n")
                numeventos_exclu+=1
                linea_aux=''
                lineacollect_aux=''
            
        #numeventos+=1

        # if pregunta si en los sfile hay lecturas de una estación determinada
        #if datoslinea[0]=='CCHI' or datoslinea[0]=='CCH2':
            # se puede mostrar o guardar el evento en otro txt si se necesita    
            #print(datoslinea)
            #time.sleep(5)
    else:
        lineacollect=''

excluidostmp1=open("excluidostmp1.txt")
excluidos=open("excluidos.txt", "w")

for lineatxt in excluidostmp1:
    linea=''
    elemento=''
    pos=0
    evento=lineatxt.split()
    for dato in evento:
        if pos <= 4:
            if (pos==2 or pos==3):
                if len(dato)==1:
                    elemento='0'+dato
                    linea=linea+elemento
                else:
                    elemento=dato
                    linea=linea+elemento+' '
            else: 
                if (pos==1 or pos==2) and (len(dato)==2 and dato[0]=='0'):
                    elemento=dato[-1]
                    linea=linea+elemento+' '
                else:
                    elemento=dato
                    linea=linea+elemento+' '

            pos=pos+1
        else:
            linea=linea+dato+' '
        
    lineafinal=linea.split()
    pos=-1
    lineafinaltxt=''
    for elemento in lineafinal:
        pos=pos+1 
        if pos==1:
            if len(elemento)<4:
                lineafinaltxt=lineafinaltxt+elemento
            else:
                lineafinaltxt=lineafinaltxt+elemento+' '

        else:
            lineafinaltxt=lineafinaltxt+elemento+' '

    lineatxt=lineafinaltxt
    lineafinaltxt=''
    lineafinal=lineatxt.split()
    pos=-1
    lineafinaltxt=''
    for elemento in lineafinal:
        pos=pos+1 
        if pos==2:
            if len(elemento)<4:
                lineafinaltxt=lineafinaltxt+elemento
            else:
                lineafinaltxt=lineafinaltxt+elemento+' '

        else:
            lineafinaltxt=lineafinaltxt+elemento+' '    

    lineatxt=lineafinaltxt
    lineafinaltxt=''
    excluidos.write(lineatxt+"\n")
    #remove("excluidostmp1.txt")

# aca debo abrir excluidos.txt y revisar eventos con horas mayores a 2359 y dejarlos en otro txt y solo
# dejar los eventos con horas correctas
# print("----------------------------------- Salida -----------------------------------")
#print("\nAnalizando datos...")
print('\nEventos a analizar:',numeventos_update+numeventos_exclu)
#print(newcollect.name, 'generado')         

    