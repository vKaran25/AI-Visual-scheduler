const loadjoke = async () => {
    try{
        const fetchjoke = await fetch('https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit&type=single',{
            headers:{
                Accept:'application/json'
            }
        });

        const factdata = await fetchjoke.json()
        document.getElementById('jokecontainer').innerHTML = factdata.joke
    }
    catch(error){
        console.log(error)
    }
}
document.getElementById('jokebtn').addEventListener("click",loadjoke)



//https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit
